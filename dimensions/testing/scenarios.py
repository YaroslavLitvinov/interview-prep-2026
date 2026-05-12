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

from dimensions.uipath import format_uipath, parse, resolve, stability
from dimensions.uipath.derive import derive_all


# ── models ────────────────────────────────────────────────────────────────


class Scenario(BaseModel):
    """One test case for one plugin.

    Live-capture driven: ``url`` is loaded through the plugin's real
    protocol; ``tests`` declares assertions against the resulting walk.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    plugin: str
    url: str
    tests: Dict[str, Dict[str, Dict[str, Any]]] = Field(default_factory=dict)


# ── discovery ─────────────────────────────────────────────────────────────


DEFAULT_SCENARIO_ROOT = Path("tests/scenarios")


def discover(
    root: Optional[Path] = None,
    *,
    roots: Optional[Iterable[Path]] = None,
) -> List[Scenario]:
    """Find every Scenario JSON below the given root(s).

    Recursive glob; files that don't parse as a Scenario are silently
    skipped. Identity is ``(plugin, name)`` — duplicate pairs raise
    ``ScenarioCollision``.
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
    isn't a Scenario."""
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

    return scenario.model_copy(update={
        "url": _URL_VAR_RE.sub(_replace, scenario.url),
    })


# ── test evaluation ───────────────────────────────────────────────────────


def evaluate_tests(
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
    """Strict `resolve` first; if no match, try suffix-match.

    Suffix match: the query is a tail of exactly one node's canonical
    UIPath. Lets authors write short, leaf-anchored paths (e.g.
    `h1#interview-prep-2026`) instead of the full canonical chain
    through every testid'd Streamlit ancestor. Ambiguous suffix
    matches (≥2 hits) return None — same rule as strict resolve.
    """
    node = resolve(query, walk)
    if node is not None:
        return node
    if not walk:
        return None
    target = format_uipath(query)
    needle = "><" + target + "<"  # bracketed to force segment-boundary
    paths = derive_all(walk)
    matches = []
    for idx, p in paths.items():
        s = format_uipath(p)
        if s == target or s.endswith(">" + target):
            matches.append(idx)
    if len(matches) != 1:
        return None
    by_idx = {n["idx"]: n for n in walk}
    return by_idx[matches[0]]


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
        actual = bool(node.get("visible", True))
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
