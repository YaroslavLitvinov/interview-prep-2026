"""Stability scoring for UIPaths.

A path's stability tier predicts how likely it is to survive recapture.
Authors writing scenarios get a visible warning when targeting a WEAK
path; CI lint can require non-WEAK targets.
"""

from __future__ import annotations

from enum import Enum

from dimensions.uipath.grammar import SelectorKind, UIPath


class Stability(str, Enum):
    STRONG = "strong"   # at least one segment carries testid or id
    MEDIUM = "medium"   # at least one role+name or name selector; no testid/id
    WEAK = "weak"       # only structural / :nth fallback


def stability(path: UIPath) -> Stability:
    has_strong = False
    has_medium = False
    for seg in path.segments:
        for sel in seg.selectors:
            if sel.kind in (SelectorKind.TESTID, SelectorKind.ID):
                has_strong = True
            elif sel.kind in (SelectorKind.ROLE, SelectorKind.NAME):
                has_medium = True
    if has_strong:
        return Stability.STRONG
    if has_medium:
        return Stability.MEDIUM
    return Stability.WEAK
