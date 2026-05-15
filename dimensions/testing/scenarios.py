"""Scenario shape, on-disk discovery, and test evaluation.

A Scenario declares one test case: a URL to load and a set of
assertions against the resulting page. The framework opens the URL
through the plugin's real protocol (Playwright for visual), captures
the live DOM, then evaluates each test in the ``tests`` dict.

Scenario JSON shape::

    {
      "name":   "welcome_text",
      "plugin": "visual",
      "url":    "${home}",                    # ${name} → config.urls.<name>
      "tests": {
        "<test_name>": {
          "<uipath_string>": {
            "text":    "expected text",
            "visible": true
          },
          ...
        },
        ...
      }
    }

Discovery: every ``*.json`` under ``tests/scenarios/`` (recursive) is
parsed; files that don't validate are silently skipped. Identity is
``(plugin, name)``; duplicate pairs raise ``ScenarioCollision``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)
from typing import Literal

from dimensions.schema.filter import FilterSpec
from dimensions.uipath import format_uipath, parse, resolve, stability
from dimensions.uipath.derive import derive_all


# ── models ────────────────────────────────────────────────────────────────


class FlowStep(BaseModel):
    """One step inside a flow scenario.

    Long form: ``{"dim": "cli", "scenario": "list_works",
                  "halt_on_error": false}``.
    Always-required: ``dim`` + ``scenario``. ``halt_on_error: None``
    means inherit the flow's default.
    """

    model_config = ConfigDict(extra="forbid")

    dim:           str
    scenario:      str
    halt_on_error: Optional[bool] = None


class Flow(BaseModel):
    """A composite scenario — runs other (unit) scenarios in order.

    ``kind: "flow"`` distinguishes it from a unit Scenario at parse time.
    Each step references a unit by ``(dim, scenario)``. Step results
    accumulate into a single flow envelope persisted progressively
    (one write per step transition).
    """

    model_config = ConfigDict(extra="forbid")

    name:          str
    kind:          Literal["flow"]
    steps:         List[FlowStep] = Field(default_factory=list)
    halt_on_error: bool = True


class Scenario(BaseModel):
    """One test case for one plugin.

    Per-plugin payload fields:

    * visual — ``url`` (required), tests target UIPaths
    * cli    — ``run`` (required, string or argv list), ``cwd``, ``env``,
               ``timeout_s``; tests target output fields (``exit_code``,
               ``stdout``, ``stderr``, ``duration_ms``)

    The framework dispatches by ``plugin`` at capture / evaluation time.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    plugin: str

    # visual dim
    url: Optional[str] = None

    # cli dim
    run: Optional[Any] = None   # str | List[str]
    cwd: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)
    timeout_s: Optional[float] = None

    tests: Dict[str, Dict[str, Dict[str, Any]]] = Field(default_factory=dict)

    # Optional scenario-level filter — applied to the captured State
    # before observations are emitted. Merged with any config-level
    # protocol_defaults / dimension filter.
    filter: Optional[FilterSpec] = None


# ── discovery ─────────────────────────────────────────────────────────────


DEFAULT_SCENARIO_ROOT = Path("tests/dimensions/scenarios")


def discover(
    root: Optional[Path] = None,
    *,
    roots: Optional[Iterable[Path]] = None,
) -> List[Scenario]:
    """Find every unit Scenario JSON below the given root(s).

    Flow scenarios (``kind: "flow"``) are skipped here; use
    ``discover_flows`` for those.
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


def discover_flows(
    roots: Optional[Iterable[Path]] = None,
) -> List[Flow]:
    """Find every Flow JSON below the given root(s).

    A flow JSON file is recognized by ``"kind": "flow"`` at the top
    level. Flows can live anywhere under the scenario_roots tree —
    convention is ``tests/dimensions/flows/`` but discovery is by
    content, not by directory.
    """
    if roots is None:
        roots = [DEFAULT_SCENARIO_ROOT, Path("tests/dimensions/flows")]
    out: List[Flow] = []
    seen: Dict[str, Path] = {}
    for r in roots:
        r = Path(r)
        if not r.is_dir():
            continue
        for path in sorted(r.rglob("*.json")):
            flow = _try_load_flow(path)
            if flow is None:
                continue
            if flow.name in seen:
                raise ScenarioCollision(
                    f"duplicate flow name={flow.name!r}: "
                    f"{path} collides with {seen[flow.name]}"
                )
            seen[flow.name] = path
            out.append(flow)
    return out


def _try_load_scenario(path: Path) -> Optional[Scenario]:
    """Return the parsed Scenario at ``path`` or ``None`` if the file
    isn't a unit Scenario (or it's a flow)."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or "plugin" not in raw or "name" not in raw:
        return None
    if raw.get("kind") == "flow":
        return None
    try:
        return Scenario.model_validate(raw)
    except ValidationError:
        return None


def _try_load_flow(path: Path) -> Optional[Flow]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("kind") != "flow":
        return None
    try:
        return Flow.model_validate(raw)
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
    """Substitute every ``${name}`` in ``scenario.url`` against
    ``url_map`` (typically the plugin's ``config.urls``). Returns a
    new Scenario; the input is not mutated. Unknown keys fail fast.
    """
    def _replace(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key not in url_map:
            raise UnresolvedScenarioVar(
                f"scenario {scenario.name!r} references "
                f"${{{key}}} but no such key in `{scenario.plugin}` "
                f"plugin's `config.urls` (known: {sorted(url_map)})"
            )
        return url_map[key]

    url = scenario.url
    if url is not None:
        url = _URL_VAR_RE.sub(_replace, url)
    # Substitute in cli command components too (str run, env values).
    run = scenario.run
    if isinstance(run, str):
        run = _URL_VAR_RE.sub(_replace, run)
    elif isinstance(run, list):
        run = [
            _URL_VAR_RE.sub(_replace, x) if isinstance(x, str) else x
            for x in run
        ]
    env_vars = {
        k: (_URL_VAR_RE.sub(_replace, v) if isinstance(v, str) else v)
        for k, v in (scenario.env or {}).items()
    }
    return scenario.model_copy(update={
        "url": url, "run": run, "env": env_vars,
    })


# ── test evaluation ───────────────────────────────────────────────────────


def evaluate_tests(
    scenario: Scenario,
    envelopes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Dispatch by ``scenario.plugin`` to the right per-dim evaluator."""
    if scenario.plugin == "cli":
        return _evaluate_cli_tests(scenario, envelopes)
    return _evaluate_visual_tests(scenario, envelopes)


def _evaluate_visual_tests(
    scenario: Scenario,
    envelopes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluate every test in ``scenario.tests`` against the live walk
    derived from the captured envelopes' ``page.dom_tree`` payload.

    Returns::

        {
          "tests": [
            {
              "name":    <test_name>,
              "passed":  bool,
              "checks":  [
                {"uipath":..., "prop":..., "expected":..., "actual":...,
                 "passed": bool, "detail":...}
              ],
              "violations": [<short str>],
              "checked":   <int>,
            },
            ...
          ],
          "passed":      <bool>,        # all tests passed
          "violations":  [<all violations across tests>],
          "checked":     <int>,
          "stability":   {"STRONG": n, "MEDIUM": n, "WEAK": n},
        }
    """
    walk = _walk_from_envelopes(envelopes)
    tests_out: List[Dict[str, Any]] = []
    all_violations: List[str] = []
    total_checked = 0
    tier_summary: Dict[str, int] = {"STRONG": 0, "MEDIUM": 0, "WEAK": 0}

    for test_name, assertions in (scenario.tests or {}).items():
        test_checks: List[Dict[str, Any]] = []
        test_violations: List[str] = []

        for uipath_str, expected in assertions.items():
            try:
                upath = parse(uipath_str)
            except Exception as exc:  # noqa: BLE001
                msg = f"{test_name}: invalid UIPath {uipath_str!r}: {exc}"
                test_violations.append(msg)
                all_violations.append(msg)
                test_checks.append({
                    "uipath": uipath_str, "prop": None,
                    "expected": None, "actual": None,
                    "passed": False, "detail": "invalid UIPath",
                })
                total_checked += 1
                continue

            tier = stability(upath).value.upper()
            tier_summary[tier] = tier_summary.get(tier, 0) + 1

            node = _resolve_with_suffix_fallback(upath, walk)
            if node is None:
                msg = (
                    f"{test_name}: {uipath_str} not found in live DOM"
                )
                test_violations.append(msg)
                all_violations.append(msg)
                test_checks.append({
                    "uipath": uipath_str, "prop": None,
                    "expected": None, "actual": None,
                    "passed": False, "detail": "not found",
                })
                total_checked += 1
                continue

            for prop, want in (expected or {}).items():
                total_checked += 1
                got, ok = _check_prop(node, prop, want)
                row = {
                    "uipath":   uipath_str,
                    "prop":     prop,
                    "expected": want,
                    "actual":   got,
                    "passed":   ok,
                    "detail":   "" if ok else f"{prop}={got!r} != {want!r}",
                }
                test_checks.append(row)
                if not ok:
                    msg = (
                        f"{test_name}: {uipath_str}.{prop} "
                        f"= {got!r} (expected {want!r})"
                    )
                    test_violations.append(msg)
                    all_violations.append(msg)

        tests_out.append({
            "name":       test_name,
            "passed":     not test_violations,
            "checks":     test_checks,
            "violations": test_violations,
            "checked":    len(test_checks),
        })

    return {
        "tests":      tests_out,
        "passed":     not all_violations,
        "violations": all_violations,
        "checked":    total_checked,
        "stability":  tier_summary,
    }


def _resolve_with_suffix_fallback(
    query, walk: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Three-tier resolver for filtered/aggressive captures.

    1. **Strict** — exact canonical path equality.
    2. **Suffix** — query is a trailing segment of some derived path
       (lets authors write leaf-anchored paths like
       ``h1#interview-prep-2026`` instead of the full chain).
    3. **Leaf-only** — query's last segment equals derived's last
       segment. Survives aggressive filtering that drops ancestors,
       making the canonical path shorter than what the scenario wrote.

    Each tier requires *exactly one* match; ambiguous results escalate
    to the next tier (and ultimately return None if no tier is unique).
    """
    node = resolve(query, walk)
    if node is not None:
        return node
    if not walk:
        return None
    target = format_uipath(query)
    target_leaf = target.rsplit(">", 1)[-1] if ">" in target else target
    paths = derive_all(walk)
    by_idx = {n["idx"]: n for n in walk}

    # Tier 2: suffix match.
    suffix_matches = [
        idx for idx, p in paths.items()
        if format_uipath(p).endswith(">" + target)
    ]
    if len(suffix_matches) == 1:
        return by_idx[suffix_matches[0]]

    # Tier 3: leaf-only match.
    leaf_matches = [
        idx for idx, p in paths.items()
        if format_uipath(p).rsplit(">", 1)[-1] == target_leaf
    ]
    if len(leaf_matches) == 1:
        return by_idx[leaf_matches[0]]
    return None


def _evaluate_cli_tests(
    scenario: Scenario,
    envelopes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluate CLI assertions against the captured command envelope.

    Field selectors: ``exit_code``, ``stdout``, ``stderr``, ``duration_ms``.
    Predicates: ``equals``, ``contains``, ``empty`` (bool), ``matches``
    (regex), ``min``, ``max``.
    """
    import re as _re

    # Locate the cli envelope (capture under namespaced envelope name).
    env = next(
        (e for e in envelopes if e.get("protocol") == "subprocess"),
        envelopes[0] if envelopes else None,
    )
    obs_by_id: Dict[str, Dict[str, Any]] = {}
    if env is not None:
        for o in env.get("observations", []):
            obs_by_id[o.get("id", "")] = o

    def _field(name: str):
        if name == "exit_code":
            o = obs_by_id.get("cli.exit_code") or {}
            return o.get("value")
        if name == "stdout":
            o = obs_by_id.get("cli.stdout") or {}
            return (o.get("data") or {}).get("text", "")
        if name == "stderr":
            o = obs_by_id.get("cli.stderr") or {}
            return (o.get("data") or {}).get("text", "")
        if name == "duration_ms":
            o = obs_by_id.get("cli.duration_ms") or {}
            return o.get("value")
        return None

    def _check(actual, predicate: str, expected) -> Tuple[bool, str]:
        if predicate == "equals":
            ok = actual == expected
            return ok, "" if ok else f"got {actual!r}, expected {expected!r}"
        if predicate == "contains":
            ok = str(expected) in str(actual or "")
            return ok, "" if ok else f"{expected!r} not found in output"
        if predicate == "matches":
            ok = bool(_re.search(str(expected), str(actual or "")))
            return ok, "" if ok else f"no match for /{expected}/"
        if predicate == "empty":
            is_empty = not bool(str(actual or "").strip())
            ok = is_empty == bool(expected)
            return ok, "" if ok else (
                "expected empty, got content" if expected
                else "expected non-empty, got empty"
            )
        if predicate == "min":
            ok = actual is not None and actual >= expected
            return ok, "" if ok else f"{actual} < {expected}"
        if predicate == "max":
            ok = actual is not None and actual <= expected
            return ok, "" if ok else f"{actual} > {expected}"
        return False, f"unknown predicate {predicate!r}"

    tests_out: List[Dict[str, Any]] = []
    all_violations: List[str] = []
    total_checked = 0

    for test_name, assertions in (scenario.tests or {}).items():
        test_checks: List[Dict[str, Any]] = []
        test_violations: List[str] = []
        for field_name, predicates in (assertions or {}).items():
            actual = _field(field_name)
            for predicate, expected in (predicates or {}).items():
                total_checked += 1
                ok, detail = _check(actual, predicate, expected)
                test_checks.append({
                    "field":     field_name,
                    "predicate": predicate,
                    "expected":  expected,
                    "actual":    actual,
                    "passed":    ok,
                    "detail":    detail,
                })
                if not ok:
                    msg = f"{test_name}: {field_name}.{predicate} — {detail}"
                    test_violations.append(msg)
                    all_violations.append(msg)
        tests_out.append({
            "name":       test_name,
            "passed":     not test_violations,
            "checks":     test_checks,
            "violations": test_violations,
            "checked":    len(test_checks),
        })

    return {
        "tests":      tests_out,
        "passed":     not all_violations,
        "violations": all_violations,
        "checked":    total_checked,
        "stability":  {"STRONG": 0, "MEDIUM": 0, "WEAK": 0},
    }


def _check_prop(
    node: Dict[str, Any], prop: str, expected: Any,
) -> Tuple[Any, bool]:
    """Check one expected property against the captured node.

    Supported props:
        text     — node's text content (trimmed equality)
        visible  — node.visible (bool)
        role     — node.role / attributes.role
        tag      — node.tag (lowercase equality)
        contains — substring match against node.text
    """
    if prop == "text":
        actual = (node.get("text") or "").strip()
        return actual, actual == (expected or "").strip()
    if prop == "contains":
        actual = (node.get("text") or "")
        return actual, str(expected) in actual
    if prop == "visible":
        v = node.get("visible")
        # ``None`` means "field absent / unknown" (often dropped by the
        # filter layer). Treat as visible — matches the pre-filter
        # default of ``node.get("visible", True)``.
        actual = True if v is None else bool(v)
        return actual, actual == bool(expected)
    if prop == "tag":
        actual = (node.get("tag") or "").lower()
        return actual, actual == str(expected).lower()
    if prop == "role":
        attrs = node.get("attributes") or {}
        actual = attrs.get("role") or node.get("role")
        return actual, actual == expected
    # Unknown prop: fall through to attribute / direct field lookup.
    attrs = node.get("attributes") or {}
    if prop in attrs:
        return attrs[prop], attrs[prop] == expected
    actual = node.get(prop)
    return actual, actual == expected


def _walk_from_envelopes(envelopes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reconstruct a flat dom_walk from the ``page.dom_tree`` payload."""
    for env in envelopes:
        for obs in env.get("observations", []):
            if obs.get("id") == "page.dom_tree":
                root = (obs.get("data") or {}).get("root")
                if root is None:
                    return []
                return _flatten_tree(root)
    return []


def _flatten_tree(root: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pre-order traversal → flat walk with idx/parent assigned."""
    out: List[Dict[str, Any]] = []

    def visit(node: Dict[str, Any], parent_idx: int) -> None:
        idx = len(out)
        flat = {k: v for k, v in node.items() if k != "children"}
        flat["idx"] = idx
        flat["parent"] = parent_idx
        out.append(flat)
        for child in (node.get("children") or []):
            visit(child, idx)

    visit(root, -1)
    return out


__all__ = [
    "Scenario",
    "ScenarioCollision",
    "UnresolvedScenarioVar",
    "discover",
    "evaluate_tests",
    "resolve_scenario_urls",
]
