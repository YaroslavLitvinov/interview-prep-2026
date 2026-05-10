"""Derive canonical UIPaths from a captured DOM walk.

The walker chooses the *strongest* identifier per segment, in priority
order: ``testid → id → role+name → name → :nth``. Pure-structural
``:nth(N)`` is used only when no stronger selector exists *and* siblings
would otherwise collide.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from dimensions.uipath.grammar import (
    Segment,
    Selector,
    SelectorKind,
    UIPath,
)


def from_node(
    node: Dict[str, Any], walk: List[Dict[str, Any]],
) -> UIPath:
    """Canonical shortest UIPath for one node within `walk`.

    Computes the entire walk's paths in one pass — for hot loops use
    `derive_all` directly and reuse the result.
    """
    return derive_all(walk)[node["idx"]]


def derive_all(walk: List[Dict[str, Any]]) -> Dict[int, UIPath]:
    """Compute UIPath for every node in `walk`.

    Single pre-order pass. Each node's segment is the canonical short
    form; the path is the chain from the node up to the root.
    """
    if not walk:
        return {}

    by_idx: Dict[int, Dict[str, Any]] = {n["idx"]: n for n in walk}
    children_by_parent: Dict[int, List[int]] = {}
    for n in walk:
        children_by_parent.setdefault(n["parent"], []).append(n["idx"])

    own_segment: Dict[int, Segment] = {}
    for n in walk:
        own_segment[n["idx"]] = _segment_for(n)

    # Compute :nth disambiguation only when same-tag siblings collide on
    # everything else (i.e., their non-:nth segment would be identical).
    nth_value: Dict[int, int] = {}
    for parent_idx, children in children_by_parent.items():
        # Group children by their non-:nth canonical segment string.
        from dimensions.uipath.grammar import _format_segment
        groups: Dict[str, List[int]] = {}
        for c in children:
            key = _format_segment(own_segment[c])
            groups.setdefault(key, []).append(c)
        for _, group in groups.items():
            if len(group) > 1:
                # Walk-order index becomes the :nth value (1-based).
                for pos, child_idx in enumerate(group, start=1):
                    nth_value[child_idx] = pos

    # Apply :nth where needed — produces the final segment for each node.
    final_segment: Dict[int, Segment] = {}
    for idx, seg in own_segment.items():
        if idx in nth_value:
            final_segment[idx] = Segment(
                tag=seg.tag,
                selectors=seg.selectors + (
                    Selector(kind=SelectorKind.NTH, value=str(nth_value[idx])),
                ),
            )
        else:
            final_segment[idx] = seg

    # Build paths from root down via parent chain.
    out: Dict[int, UIPath] = {}
    for n in walk:
        chain: List[Segment] = []
        cur = n["idx"]
        while cur != -1:
            chain.append(final_segment[cur])
            cur = by_idx[cur]["parent"]
        chain.reverse()
        out[n["idx"]] = UIPath(segments=tuple(chain))
    return out


def _segment_for(node: Dict[str, Any]) -> Segment:
    """Build the canonical segment for one node — strongest selector wins.

    Priority:
      1. ``data-testid`` / ``data-test-id`` / ``data-test``
      2. ``id`` (HTML id attribute)
      3. ``role`` + accessible name (aria-label / name attribute)
      4. ``name`` (form-element name)

    No selector at all when the tag itself is sufficient (root, single-child
    chains). `:nth(N)` is appended later by `derive_all` only when needed.
    """
    tag = (node.get("tag") or "").lower() or "?"
    attrs = node.get("attributes") or {}

    testid = (
        attrs.get("data-testid")
        or attrs.get("data-test-id")
        or attrs.get("data-test")
    )
    if testid:
        return Segment(
            tag=tag,
            selectors=(Selector(kind=SelectorKind.TESTID, value=str(testid)),),
        )

    if node.get("id"):
        return Segment(
            tag=tag,
            selectors=(Selector(kind=SelectorKind.ID, value=str(node["id"])),),
        )

    role = attrs.get("role") or node.get("role")
    accessible_name = (
        attrs.get("aria-label")
        or node.get("aria_label")
        or attrs.get("name")
    )
    if role and accessible_name:
        return Segment(
            tag=tag,
            selectors=(
                Selector(kind=SelectorKind.ROLE, value=str(role)),
                Selector(kind=SelectorKind.NAME, value=str(accessible_name)),
            ),
        )

    if attrs.get("name"):
        return Segment(
            tag=tag,
            selectors=(Selector(kind=SelectorKind.NAME, value=str(attrs["name"])),),
        )

    return Segment(tag=tag, selectors=())
