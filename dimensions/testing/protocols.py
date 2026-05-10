"""Fixture-replay implementations of each `InjectionProtocol`.

Each fixture protocol is the test-time sibling of a real protocol —
same abstract base, same return type, but the source of the data is a
pre-recorded JSON fixture instead of a live system. Plugins don't need
to know which one they got.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from dimensions.kinds.visual import BrowserProtocol, PageState


class FixtureBrowserProtocol(BrowserProtocol):
    """Replay a pre-recorded PageState. No browser, no network.

    Constructed with a single fixture dict. Every `render(...)` call
    returns the same state — multi-URL scenarios that need different
    states per URL should provide a `keyed` mapping (url → fixture)
    instead of a single fixture.
    """

    name = "fixture-browser"
    engine = "fixture"

    def __init__(
        self,
        fixture: Optional[Dict[str, Any]] = None,
        *,
        keyed: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self._single = fixture
        self._keyed = dict(keyed or {})
        if not self._single and not self._keyed:
            raise ValueError("FixtureBrowserProtocol needs `fixture` or `keyed`")

    async def open(self) -> None:  # noqa: D401
        return None

    async def close(self) -> None:
        return None

    async def render(
        self,
        url: str,
        *,
        viewport: Dict[str, int],
        timeout_ms: int,
        tree_filter: Optional[List[str]] = None,
    ) -> PageState:
        data = self._keyed.get(url, self._single) or {}
        return _page_state_from_dict(data, url=url, viewport=viewport)


def _page_state_from_dict(
    data: Dict[str, Any],
    *,
    url: str,
    viewport: Dict[str, int],
) -> PageState:
    """Translate a JSON dict into a PageState. Tolerant of partial fixtures.

    `dom_walk` accepts two shapes:

      * **Flat** — a list of dicts each carrying explicit ``idx`` and
        ``parent``. The production capture form. Passed through with
        per-node defaults filling absent fields.

      * **UIPath-keyed flat map** — a dict where each key is a UIPath
        string and the value is per-node properties (``text``,
        ``computed_style`` overrides, bbox, etc). The loader parses
        each path, materialises every segment as a flat node, dedupes
        ancestors by path prefix, and auto-assigns ``idx`` / ``parent``.
        Authors write only the leaves with meaningful content; the
        loader fills in the rest with neutral defaults.

    Per-node defaults are applied either way, so any field a fixture
    omits — including ``computed_style``, bbox, ``role``, ``aria_label`` —
    gets a sane neutral value.
    """
    return PageState(
        available=bool(data.get("available", True)),
        loaded=bool(data.get("loaded", True)),
        status=int(data.get("status", 200)),
        url=str(data.get("url", url)),
        title=str(data.get("title", "")),
        viewport=dict(data.get("viewport", viewport)),
        dom_walk=_normalize_dom_walk(data.get("dom_walk")),
        screenshot=data.get("screenshot"),
        screenshot_format=str(data.get("screenshot_format", "png")),
        error=data.get("error"),
    )


# ── dom_walk normalization ────────────────────────────────────────────────


_DEFAULT_COMPUTED_STYLE: Dict[str, str] = {
    "display":          "block",
    "color":            "rgb(0,0,0)",
    "background-color": "rgba(0,0,0,0)",
    "font-family":      "system-ui",
    "font-size":        "16px",
    "font-weight":      "400",
    "z-index":          "auto",
    "opacity":          "1",
    "visibility":       "visible",
    "overflow":         "visible",
    "position":         "static",
}


def normalize_dom_walk(raw: Any) -> List[Dict[str, Any]]:
    """Public alias for `_normalize_dom_walk` — exposed for the Scenario
    validator, which needs to resolve step targets against the same
    normalized walk shape the fixture loader produces."""
    return _normalize_dom_walk(raw)


def _normalize_dom_walk(raw: Any) -> List[Dict[str, Any]]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [_node_with_defaults(n) for n in raw]
    if isinstance(raw, dict):
        return _flatten_uipath_map(raw)
    raise TypeError(
        f"dom_walk must be a list (flat) or a dict (UIPath-keyed map); "
        f"got {type(raw).__name__}"
    )


def _flatten_uipath_map(elements: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Materialise a UIPath-keyed map into a flat walk.

    Each key is parsed; every segment along the way becomes a node
    (created on first encounter, deduped on subsequent ones). Leaf
    properties are merged onto the node corresponding to the full path;
    ancestors get only structural fields plus defaults. `idx` follows
    insertion order (which is the user's authoring order, deterministic
    in JSON since Python 3.7+).
    """
    from dimensions.uipath import parse
    from dimensions.uipath.grammar import (
        SelectorKind, UIPath, format_uipath, _format_segment,
    )

    path_to_idx: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []

    for path_str, props in elements.items():
        uipath = parse(path_str)
        if not uipath.segments:
            continue
        parent_idx = -1
        n_segments = len(uipath.segments)
        for i, seg in enumerate(uipath.segments):
            sub_path = format_uipath(
                UIPath(segments=uipath.segments[: i + 1])
            )
            is_leaf = i == n_segments - 1

            if sub_path not in path_to_idx:
                node = _node_from_segment(seg)
                node["idx"] = len(out)
                node["parent"] = parent_idx
                if is_leaf:
                    node = _apply_props(node, props)
                node = _node_with_defaults(node)
                path_to_idx[sub_path] = node["idx"]
                out.append(node)
            elif is_leaf:
                # Ancestor was implicitly created earlier; now an explicit
                # listing supplies properties — merge them in.
                existing = out[path_to_idx[sub_path]]
                _merge_props(existing, props)

            parent_idx = path_to_idx[sub_path]
    return out


def _node_from_segment(seg: Any) -> Dict[str, Any]:
    """Build a partial node from a UIPath Segment.

    Selectors are translated into the matching node fields:
      [testid=X] → attributes['data-testid'] = X
      [id=X]     → id = X (and #X shorthand)
      [role=X]   → attributes['role'] = X
      [name=X]   → attributes['name'] = X
      :nth(N)    → ignored for fixture authoring (siblings should be
                   disambiguated by testid/id/name in fixtures).
    """
    from dimensions.uipath.grammar import SelectorKind

    node: Dict[str, Any] = {"tag": seg.tag, "attributes": {}}
    for sel in seg.selectors:
        if sel.kind == SelectorKind.TESTID:
            node["attributes"]["data-testid"] = sel.value
        elif sel.kind == SelectorKind.ID:
            node["id"] = sel.value
        elif sel.kind == SelectorKind.ROLE:
            node["attributes"]["role"] = sel.value
        elif sel.kind == SelectorKind.NAME:
            node["attributes"]["name"] = sel.value
        # NTH is positional; sibling ordering is the loader's job, not
        # a node attribute. Author should disambiguate with testid/name.
    return node


def _apply_props(
    node: Dict[str, Any], props: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge a leaf's property dict onto a freshly-synthesised node.

    Special-cases ``computed_style`` so values are layered onto the
    defaults rather than replacing the whole dict; for everything else
    the value from props wins.
    """
    if not props:
        return node
    for k, v in props.items():
        if k == "computed_style":
            cs = dict(node.get("computed_style") or {})
            cs.update(v or {})
            node["computed_style"] = cs
        elif k == "attributes":
            attrs = dict(node.get("attributes") or {})
            attrs.update(v or {})
            node["attributes"] = attrs
        else:
            node[k] = v
    return node


def _merge_props(
    existing: Dict[str, Any], props: Dict[str, Any],
) -> None:
    """Merge in-place — used when the same path is listed twice (rare)
    or when an ancestor is listed explicitly to override defaults."""
    if not props:
        return
    for k, v in props.items():
        if k == "computed_style":
            cs = dict(existing.get("computed_style") or {})
            cs.update(v or {})
            existing["computed_style"] = cs
        elif k == "attributes":
            attrs = dict(existing.get("attributes") or {})
            attrs.update(v or {})
            existing["attributes"] = attrs
        else:
            existing[k] = v


def _node_with_defaults(node: Dict[str, Any]) -> Dict[str, Any]:
    """Fill in every field the production capture would emit.

    Authors specify the fields that matter; the loader supplies neutral
    defaults for everything else so a node can be as small as
    ``{"tag": "div"}``.
    """
    out = dict(node)
    out.setdefault("idx", 0)
    out.setdefault("parent", -1)
    out.setdefault("kept", True)
    out.setdefault("tag", "?")
    out.setdefault("id", "")
    out.setdefault("classes", [])
    out.setdefault("attributes", {})
    out.setdefault("text", "")
    out.setdefault("x", 0)
    out.setdefault("y", 0)
    out.setdefault("width", 0)
    out.setdefault("height", 0)
    out.setdefault("z_index", 0)
    out.setdefault("position", "static")
    out.setdefault("visible", True)
    out.setdefault("role", None)
    out.setdefault("aria_label", None)
    cs = dict(_DEFAULT_COMPUTED_STYLE)
    cs.update(out.get("computed_style") or {})
    out["computed_style"] = cs
    return out


# ── dispatch ──────────────────────────────────────────────────────────────


def make_fixture_protocol(kind: str, fixture: Dict[str, Any]):
    """Pick the right fixture-protocol implementation for a Scenario.

    Currently only `browser` is implemented. New kinds (`data`, `web`)
    plug in here as their plugins arrive.
    """
    kind = (kind or "").lower()
    if kind == "browser":
        return FixtureBrowserProtocol(fixture=fixture)
    raise ValueError(
        f"unknown fixture protocol kind: {kind!r} "
        "(supported: 'browser')"
    )
