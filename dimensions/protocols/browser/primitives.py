"""Framework primitives for the Visual dimension.

The visual plugin opens two envelopes per URL — ``<url>.tree`` (page
status + hierarchical DOM with styles/layout/role)
and ``<url>.screenshot`` (PNG asset). Every helper below is a pure
function over ``(EnvelopeBuilder, PageState)`` — no I/O, no Playwright
awareness.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from dimensions.protocols.browser.injection import PageState

if TYPE_CHECKING:
    from dimensions.api import EnvelopeBuilder


DEFAULT_VIEWPORT: Dict[str, int] = {"width": 1280, "height": 720}
DEFAULT_TIMEOUT_MS: int = 10_000


def url_subject_dict(
    url: str,
    viewport: Optional[Dict[str, int]] = None,
    browser: str = "chromium",
) -> Dict[str, Any]:
    return {
        "kind": "url",
        "url": url,
        "viewport": viewport or dict(DEFAULT_VIEWPORT),
        "browser": browser,
    }


# ── envelope: <url>.tree ──────────────────────────────────────────────────


# Per-tree-node fields kept in the rendered payload (drop walk-internal keys
# like idx/parent/kept that only the assembly step needs).
_TREE_NODE_KEYS = (
    "tag", "id", "classes", "attributes", "text",
    "x", "y", "width", "height", "z_index", "position", "visible",
    "computed_style", "role", "aria_label",
)


def emit_tree(
    env: "EnvelopeBuilder",
    state: PageState,
    *,
    tree_filter: Optional[List[str]] = None,
    with_hierarchy: bool = False,
) -> None:
    """Emit the unified DOM-tree envelope.

    Observations:

      • ``page.error``           — rule_check (only on failure)
      • ``page.dom_tree``        — payload (schema=dom_tree)
      • ``page.captured``        — boolean: terminator

    Filter semantics:
      * empty/absent ``tree_filter`` — every element kept; ``skipped`` empty;
        ``root`` is the full DOM.
      * non-empty ``tree_filter`` — only matching elements kept.
        ``with_hierarchy=False`` (default): tree contains only matching
        elements, re-parented through dropped intermediates ("collapsed").
        ``with_hierarchy=True``: tree includes matching elements plus their
        ancestors back to root; non-matching ancestors carry
        ``connector=True``.
      * ``skipped`` lists every element not present in the tree, with the
        reason it was excluded.
    """
    if not state.available:
        env.boolean("page.captured", "Visual capture completed without error", False)
        env.rule_check(
            "page.error", "Visual capture surfaced an exception",
            passed=False,
            violations=[{"error": state.error or "browser unavailable"}],
            checked_count=1,
        )
        return

    if not state.loaded:
        if state.error:
            env.rule_check(
                "page.error", "Visual capture surfaced an exception",
                passed=False, violations=[{"error": state.error}], checked_count=1,
            )
        env.boolean(
            "page.captured", "Visual capture completed without error",
            state.error is None,
        )
        return

    walk = list(state.dom_walk or [])

    root, kept_count, skipped = _build_tree(
        walk, tree_filter or None, with_hierarchy,
    )
    env.payload(
        "page.dom_tree",
        "DOM tree (per-element styles, layout, role)",
        payload_schema="dom_tree",
        data={
            "root":           root,
            "node_count":     len(walk),
            "kept_count":     kept_count,
            "skipped_count":  len(skipped),
            "filter":         list(tree_filter) if tree_filter else None,
            "with_hierarchy": bool(with_hierarchy),
            "skipped":        skipped,
        },
    )

    env.payload(
        "page.screen_map",
        "Screen Map (UIPath-keyed element index)",
        payload_schema="screen_map",
        data=_build_screen_map(walk, state.url),
    )

    env.boolean("page.captured", "Visual capture completed without error", True)


def _build_screen_map(walk, url: str) -> Dict[str, Any]:
    """Flatten a DOM walk into a screen_map payload.

    The map is keyed by canonical UIPath strings; values carry just
    enough to identify and locate the element (tag, role, accessible
    name, bbox, interactivity, stability tier). The full computed style
    and attributes stay in dom_tree — screen_map is the *referenceable*
    summary, not a duplicate.
    """
    from dimensions.uipath import derive_all, format_uipath, stability

    if not walk:
        return {
            "url": url,
            "elements": {},
            "interactives": [],
            "headings": [],
            "forms": [],
        }

    paths = derive_all(walk)
    by_idx = {n["idx"]: n for n in walk}

    interactive_tags = {"a", "button", "input", "select", "textarea", "label"}
    heading_tags = {"h1", "h2", "h3", "h4", "h5", "h6"}
    form_tags = {"form"}

    elements: Dict[str, Any] = {}
    interactives: List[str] = []
    headings: List[str] = []
    forms: List[str] = []

    for idx, node in by_idx.items():
        path = paths[idx]
        key = format_uipath(path)
        attrs = node.get("attributes") or {}
        tag = (node.get("tag") or "").lower()
        role = attrs.get("role") or node.get("role")
        accessible_name = (
            attrs.get("aria-label")
            or node.get("aria_label")
            or attrs.get("name")
        )
        is_interactive = tag in interactive_tags or role in {
            "button", "link", "textbox", "checkbox", "radio", "menuitem",
        }
        elements[key] = {
            "uipath": key,
            "tag": tag,
            "role": role,
            "accessible_name": accessible_name,
            "interactive": is_interactive,
            "bbox": [
                int(node.get("x", 0)), int(node.get("y", 0)),
                int(node.get("width", 0)), int(node.get("height", 0)),
            ],
            "visible": bool(node.get("visible", True)),
            "stability": stability(path).value,
        }
        if is_interactive:
            interactives.append(key)
        if tag in heading_tags:
            headings.append(key)
        if tag in form_tags:
            forms.append(key)

    return {
        "url": url,
        "elements": elements,
        "interactives": interactives,
        "headings": headings,
        "forms": forms,
    }


def _node_view(n: Dict[str, Any]) -> Dict[str, Any]:
    return {k: n.get(k) for k in _TREE_NODE_KEYS}


def _build_tree(
    walk: List[Dict[str, Any]],
    selectors: Optional[List[str]],
    with_hierarchy: bool,
):
    """Assemble the hierarchical tree from a flat pre-order walk."""
    if not walk:
        return None, 0, []

    by_idx = {n["idx"]: n for n in walk}
    has_filter = bool(selectors)

    if has_filter:
        if with_hierarchy:
            in_tree = set()
            for n in walk:
                if n.get("kept"):
                    cur = n["idx"]
                    while cur != -1 and cur not in in_tree:
                        in_tree.add(cur)
                        cur = by_idx[cur]["parent"]
            new_parents = {idx: by_idx[idx]["parent"] for idx in in_tree}
        else:
            in_tree = {n["idx"] for n in walk if n.get("kept")}
            new_parents = {}
            for n in walk:
                if not n.get("kept"):
                    continue
                cur = n["parent"]
                while cur != -1 and not by_idx[cur].get("kept"):
                    cur = by_idx[cur]["parent"]
                new_parents[n["idx"]] = cur
        skipped = [
            {
                "tag":     by_idx[i]["tag"],
                "id":      by_idx[i].get("id", ""),
                "classes": by_idx[i].get("classes", []),
                "reason":  "no-match",
            }
            for i in range(len(walk))
            if i not in in_tree
        ]
    else:
        in_tree = set(range(len(walk)))
        new_parents = {n["idx"]: n["parent"] for n in walk}
        skipped = []

    if not in_tree:
        return None, 0, skipped

    nodes = {}
    for idx in in_tree:
        view = _node_view(by_idx[idx])
        if has_filter and with_hierarchy and not by_idx[idx].get("kept"):
            view["connector"] = True
        view["children"] = []
        nodes[idx] = view
    for idx in in_tree:
        p = new_parents[idx]
        if p in nodes:
            nodes[p]["children"].append(nodes[idx])

    roots = [idx for idx in in_tree if new_parents[idx] not in nodes]
    if len(roots) == 1:
        root = nodes[roots[0]]
    else:
        # Multiple disconnected matches → wrap in a synthetic root so the
        # tree remains a single object the renderer can walk uniformly.
        root = {"tag": "_filtered_roots", "children": [nodes[r] for r in roots]}

    kept_count = sum(1 for n in walk if n.get("kept"))
    return root, kept_count, skipped


# ── envelope: <url>.screenshot ────────────────────────────────────────────


def emit_screenshot(env: "EnvelopeBuilder", state: PageState) -> None:
    """Page screenshot — bytes go to content-addressed asset storage."""
    if state.screenshot is None:
        return
    asset = env.attach_asset(
        state.screenshot,
        mime_type="image/png" if state.screenshot_format == "png" else "image/jpeg",
        suffix=f".{state.screenshot_format}",
    )
    env.payload(
        "page.screenshot", "Page screenshot",
        payload_schema="screenshot",
        data={
            **asset,
            "format": state.screenshot_format,
            "width":  state.viewport.get("width"),
            "height": state.viewport.get("height"),
        },
    )
