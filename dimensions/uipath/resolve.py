"""Resolve a UIPath to a node within a captured DOM walk.

Returns 0 or 1 nodes — never multiple. A non-canonical path that would
match more than one node returns None instead.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from dimensions.uipath.grammar import UIPath
from dimensions.uipath.derive import derive_all
from dimensions.uipath.grammar import format_uipath


def resolve(
    path: UIPath, walk: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return the unique node matching `path`, or None.

    A path resolves iff `format_uipath(derive_all(walk)[idx]) ==
    format_uipath(path)` for exactly one `idx`. This is a strict
    same-grammar match — formatting differences (e.g. `tag#id` vs
    `tag[id=…]`) are normalised via re-formatting both sides.
    """
    if not walk:
        return None
    target = format_uipath(path)
    paths = derive_all(walk)
    matches = [
        idx for idx, p in paths.items()
        if format_uipath(p) == target
    ]
    if len(matches) != 1:
        return None
    by_idx: Dict[int, Dict[str, Any]] = {n["idx"]: n for n in walk}
    return by_idx[matches[0]]
