"""Scenario shape, on-disk discovery, and replay execution.

A Scenario binds a fixture to a plugin and a list of steps + expectations.
The replay harness runs the plugin against the fixture through a fixture
protocol and asserts every generic framework invariant plus any
scenario-specific expectations.

Scenarios are JSON files. Default discovery root is ``tests/scenarios/``;
each scenario lives at ``tests/scenarios/<plugin>/<name>.json``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
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


def discover(
    root: Optional[Path] = None,
) -> List[Scenario]:
    """Find every Scenario JSON below `root`.

    Layout convention: ``<root>/<plugin>/<scenario>.json``. The plugin
    field defaults to the scenario file's parent directory name when
    omitted in the JSON.
    """
    root = Path(root) if root else Path("tests/scenarios")
    if not root.is_dir():
        return []
    out: List[Scenario] = []
    for path in sorted(root.glob("*/*.json")):
        raw = json.loads(path.read_text())
        raw.setdefault("plugin", path.parent.name)
        raw.setdefault("name", path.stem)
        out.append(Scenario.model_validate(raw))
    return out


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
    """
    from dimensions.testing.protocols import make_fixture_protocol
    from dimensions.testing.properties import (
        assert_generic, assert_expectations,
    )

    proto = make_fixture_protocol(scenario.protocol, scenario.fixture)
    plugin = _instantiate_plugin(plugin_class, proto, scenario)
    envelopes = await _drive_plugin(plugin)
    assert_generic(envelopes)
    assert_expectations(envelopes, scenario.expectations)
    return envelopes


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
