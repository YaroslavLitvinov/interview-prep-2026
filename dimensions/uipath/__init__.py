"""UIPath — canonical, content-derived element locators.

A `UIPath` identifies one element on one screen. Class-free,
recapture-stable, human-readable, deterministically resolvable.

Everything that needs to refer to a UI element — the diff layer's
matching algorithm, scenario step targets, comment anchors at element
granularity, LLM-generated test specs — uses this single primitive.

Typical usage::

    from dimensions.uipath import derive_all, format_uipath, parse, resolve

    # During capture / diff: build paths for every node in a walk.
    paths = derive_all(dom_walk)              # Dict[idx, UIPath]
    keys  = {idx: format_uipath(p) for idx, p in paths.items()}

    # Anywhere else: from a string, locate the node.
    p = parse("main > section[testid=users-form] > input[name=name]")
    node = resolve(p, dom_walk)               # Optional[Dict]

The grammar is a strict superset of the original ``_path_keys`` output,
so existing diff-layer paths parse identically. Richer selectors
(``[testid=…]``, ``[role=…]``, ``[name=…]``) are emitted when the
captured walk supplies them.
"""

from dimensions.uipath.grammar import (
    Segment,
    Selector,
    SelectorKind,
    UIPath,
    format_uipath,
    parse,
)
from dimensions.uipath.derive import derive_all, from_node
from dimensions.uipath.resolve import resolve
from dimensions.uipath.score import Stability, stability

__all__ = [
    "Segment",
    "Selector",
    "SelectorKind",
    "Stability",
    "UIPath",
    "derive_all",
    "format_uipath",
    "from_node",
    "parse",
    "resolve",
    "stability",
]
