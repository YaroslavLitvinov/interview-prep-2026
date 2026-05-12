"""Scenario shape, on-disk discovery, and replay execution.

A Scenario binds a fixture to a plugin and a list of steps + expectations.
The replay harness runs the plugin against the fixture through a fixture
protocol and asserts every generic framework invariant plus any
scenario-specific expectations.

Scenarios are JSON files. Default discovery root is ``tests/scenarios/``;
files may live at any depth under it. The ``plugin`` and ``name`` fields
on each scenario are authoritative — the directory layout is purely
organisational. Extra roots can be supplied to ``discover()`` directly or
configured via ``scenario_roots:`` in ``dimensions.config.yaml``.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from dimensions.uipath import UIPath, format_uipath, parse, resolve, stability


# ── models ────────────────────────────────────────────────────────────────


class Step(BaseModel):
    """A single action or assertion within a scenario.

    `target` is a typed `UIPath` — UIPath strings in the JSON are parsed
    at model-validation time. A syntactically invalid path fails
    immediately with a Pydantic ValidationError. Resolution against the
    fixture's dom_walk happens later, in the parent Scenario validator
    (which has access to the fixture).
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    action: Literal[
        "visit", "click", "type", "submit",
        "expect_text", "expect_visible",
    ]
    url: Optional[str] = None
    target: Optional[UIPath] = None
    value: Optional[str] = None

    @field_validator("target", mode="before")
    @classmethod
    def _parse_target(cls, v: Any) -> Any:
        """Accept either a UIPath instance or a string in canonical form."""
        if v is None or isinstance(v, UIPath):
            return v
        if isinstance(v, str):
            return parse(v)
        raise TypeError(
            f"step.target must be a UIPath string or instance; "
            f"got {type(v).__name__}"
        )

    @field_serializer("target")
    def _serialize_target(self, v: Optional[UIPath]) -> Optional[str]:
        return None if v is None else format_uipath(v)


class Scenario(BaseModel):
    """One frozen test case for one plugin."""

    model_config = ConfigDict(extra="forbid")

    name: str
    plugin: str
    protocol: str = "browser"
    fixture: Dict[str, Any] = Field(default_factory=dict)
    steps: List[Step] = Field(default_factory=list)
    expectations: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _resolve_step_targets(self) -> "Scenario":
        """Confabulation guard: every step.target must resolve in the
        fixture's dom_walk. A typo, a stale path, or an LLM-invented
        element fails here — before any test runs.
        """
        # Lazy import to keep the protocols/scenarios cycle one-way.
        from dimensions.testing.protocols import normalize_dom_walk

        walk = normalize_dom_walk(self.fixture.get("dom_walk"))
        for i, step in enumerate(self.steps):
            if step.target is None:
                continue
            node = resolve(step.target, walk)
            if node is None:
                raise ValueError(
                    f"scenario {self.name!r} step {i} "
                    f"({step.action}): target "
                    f"{format_uipath(step.target)!r} does not resolve "
                    f"in fixture's dom_walk."
                )
        return self

    def target_stability(self) -> Dict[int, str]:
        """Stability tier per step (by index). Useful for surfacing
        WEAK-target warnings to reviewers."""
        return {
            i: stability(step.target).value
            for i, step in enumerate(self.steps)
            if step.target is not None
        }


# ── discovery ─────────────────────────────────────────────────────────────


DEFAULT_SCENARIO_ROOT = Path("tests/scenarios")


def discover(
    root: Optional[Path] = None,
    *,
    roots: Optional[Iterable[Path]] = None,
) -> List[Scenario]:
    """Find every Scenario JSON below the given root(s).

    Every ``*.json`` at any depth under each root is parsed; files that
    aren't valid Scenarios are skipped silently. Identity is
    ``(plugin, name)`` — both required JSON fields. Two files producing
    the same identity raise ``ScenarioCollision`` so duplicate authoring
    is caught at discovery time.

    Resolution order:
      * ``root`` (singular) — back-compat for the old single-root call.
      * ``roots`` (plural) — explicit list, used as-is.
      * neither — the default ``tests/scenarios/`` directory.
    """
    if root is not None and roots is not None:
        raise TypeError("pass either `root` or `roots`, not both")
    if roots is None:
        roots = [root] if root is not None else [DEFAULT_SCENARIO_ROOT]

    out: List[Scenario] = []
    seen: Dict[tuple, Path] = {}
    for r in roots:
        r = Path(r)
        if not r.is_dir():
            continue
        for path in sorted(r.rglob("*.json")):
            scenario = _try_load_scenario(path)
            if scenario is None:
                continue
            key = (scenario.plugin, scenario.name)
            if key in seen:
                raise ScenarioCollision(
                    f"duplicate scenario plugin={key[0]!r} name={key[1]!r}: "
                    f"{path} collides with {seen[key]}"
                )
            seen[key] = path
            out.append(scenario)
    return out


def _try_load_scenario(path: Path) -> Optional[Scenario]:
    """Return the parsed Scenario at ``path`` or ``None`` if the file
    isn't a Scenario. Invalid JSON, missing required fields, and
    unrelated JSON documents under the root all silently skip."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or "plugin" not in raw or "name" not in raw:
        return None
    try:
        return Scenario.model_validate(raw)
    except ValidationError:
        return None


class ScenarioCollision(ValueError):
    """Two scenarios under discovery share the same ``(plugin, name)``."""


# ── URL var substitution ──────────────────────────────────────────────────


_URL_VAR_RE = re.compile(r"\$\{([^${}]+)\}")


class UnresolvedScenarioVar(ValueError):
    """A scenario references ``${name}`` which is not in the URL map."""


def resolve_scenario_urls(
    scenario: Scenario, url_map: Dict[str, str],
) -> Scenario:
    """Substitute every ``${name}`` placeholder in the scenario against
    ``url_map`` (typically the plugin's ``config.urls`` from
    ``dimensions.config.yaml``).

    Substituted sites: ``fixture.url``, ``fixture.title``, every value
    under ``expectations.urls``. Other fields are left untouched —
    ``fixture.dom_walk`` keys are UIPaths, not URLs.

    Unknown keys fail fast with ``UnresolvedScenarioVar``; silent
    partial substitution would let scenarios run with broken URLs.

    Returns a new ``Scenario`` instance; the input is not mutated.
    """
    def _sub(s: Any) -> Any:
        if not isinstance(s, str):
            return s

        def _replace(match: "re.Match[str]") -> str:
            key = match.group(1)
            if key not in url_map:
                raise UnresolvedScenarioVar(
                    f"scenario {scenario.name!r} references "
                    f"${{{key}}} but no such key in `{scenario.plugin}` "
                    f"plugin's `config.urls` (known: {sorted(url_map)})"
                )
            return url_map[key]

        return _URL_VAR_RE.sub(_replace, s)

    fixture = dict(scenario.fixture or {})
    if "url" in fixture:
        fixture["url"] = _sub(fixture["url"])
    if "title" in fixture:
        fixture["title"] = _sub(fixture["title"])

    expectations = dict(scenario.expectations or {})
    urls = expectations.get("urls")
    if isinstance(urls, dict):
        expectations["urls"] = {k: _sub(v) for k, v in urls.items()}

    return scenario.model_copy(update={
        "fixture": fixture,
        "expectations": expectations,
    })


# ── replay ────────────────────────────────────────────────────────────────


async def run_scenario(
    scenario: Scenario,
    plugin_class: type,
) -> List[Dict[str, Any]]:
    """Execute one scenario through `plugin_class`. Returns the produced
    envelopes (raw dicts, post-validation).

    Asserts:
      * every framework-level generic property
      * any scenario-specific expectations declared in the JSON
      * any read-only step assertions (expect_text, expect_visible)
        against the fixture's resolved walk
    """
    from dimensions.testing.protocols import (
        make_fixture_protocol, normalize_dom_walk,
    )
    from dimensions.testing.properties import (
        assert_generic, assert_expectations,
    )

    proto = make_fixture_protocol(scenario.protocol, scenario.fixture)
    plugin = _instantiate_plugin(plugin_class, proto, scenario)
    envelopes = await _drive_plugin(plugin)
    assert_generic(envelopes)
    assert_expectations(envelopes, scenario.expectations)

    walk = normalize_dom_walk(scenario.fixture.get("dom_walk"))
    _run_expect_steps(scenario, walk)
    return envelopes


def _run_expect_steps(scenario: "Scenario", walk: List[Dict[str, Any]]) -> None:
    """Run read-only step assertions against the fixture walk.

    Action steps (visit/click/type/submit) are recorded but skipped —
    fixtures don't have a live browser to act against. A future
    state-machine fixture form will let action steps transition between
    captured states; for now the framework only executes assertions.
    """
    for i, step in enumerate(scenario.steps):
        if step.target is None:
            continue
        if step.action == "expect_text":
            node = resolve(step.target, walk)
            actual = (node.get("text") or "").strip() if node else ""
            expected = (step.value or "").strip()
            if actual != expected:
                raise AssertionError(
                    f"scenario {scenario.name!r} step {i} expect_text: "
                    f"target {format_uipath(step.target)!r} text "
                    f"{actual!r} != expected {expected!r}"
                )
        elif step.action == "expect_visible":
            node = resolve(step.target, walk)
            if node is None or not bool(node.get("visible", True)):
                raise AssertionError(
                    f"scenario {scenario.name!r} step {i} expect_visible: "
                    f"target {format_uipath(step.target)!r} is not visible"
                )
        # Other actions (visit/click/type/submit) are intentional no-ops
        # in fixture replay. They're preserved in the model so a future
        # state-machine fixture form (or a real-browser executor) can
        # honour them without changing the data contract.


def _instantiate_plugin(plugin_class, proto, scenario: Scenario):
    """Construct the plugin with a single dummy URL/source.

    Each kind is a special case until the framework learns to introspect
    plugin constructors. Today we only support the visual kind.
    """
    if scenario.protocol == "browser":
        urls = scenario.expectations.get("urls") or {"main": "https://fixture.test/"}
        return plugin_class(urls=urls, browser=proto)
    raise ValueError(
        f"don't know how to instantiate plugin for protocol "
        f"{scenario.protocol!r}"
    )


async def _drive_plugin(plugin) -> List[Dict[str, Any]]:
    """Run plugin.collect through a minimal CollectionContext that
    captures finalized envelopes into a list, bypassing disk I/O.

    The context is intentionally tiny — it only implements what the
    visual plugin currently needs (envelope opening + asset attachment).
    """
    captured: List[Dict[str, Any]] = []
    ctx = _CollectingContext(captured, plugin.name, plugin.category)
    await plugin.collect(ctx)
    return captured


class _CollectingContext:
    """A test-only CollectionContext that builds envelopes in memory."""

    def __init__(self, captured: List[Dict[str, Any]], dim: str, category: str):
        self._captured = captured
        self._dim = dim
        self._category = category

    def envelope(
        self,
        *,
        name: str = "main",
        subject: Optional[Dict[str, Any]] = None,
    ):
        from dimensions.api import EnvelopeBuilder
        return _EnvelopeFinaliser(
            EnvelopeBuilder(
                self._dim, self._category,
                subject=subject or {},
                envelope_name=name,
            ),
            self._captured,
        )


class _EnvelopeFinaliser:
    """Sync context manager that finalises an envelope into a dict."""

    def __init__(self, builder, captured: List[Dict[str, Any]]):
        self._builder = builder
        self._captured = captured

    def __enter__(self):
        return self._builder

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            return False
        self._captured.append({
            "dimension": self._builder.dimension,
            "category": self._builder.category,
            "envelope_name": self._builder._envelope_name,
            "subject": self._builder.subject,
            "observations": list(self._builder.observations),
        })
        return False
