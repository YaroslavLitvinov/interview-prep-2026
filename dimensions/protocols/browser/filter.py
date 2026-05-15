"""Apply a FilterSpec to a PageState (DOM-walk filtering).

Selector grammar = CSS subset, comma-grouped:

    div                       tag match
    div[testid]               tag + attribute present (testid → data-testid)
    div[testid=stApp]         tag + attribute equals value
    [data-testid]             attribute present
    #my-id                    id attribute
    .my-class                 single class
    h1, h2, h3                comma-separated OR

Field whitelisting — `FilterRule.fields` entries:

    "tag"                     keep the top-level "tag" field
    "attributes.data-testid"  keep only that key inside "attributes" dict
    "*"                       keep everything (explicit, same as empty list)

Value whitelisting — `FilterSpec.values`:

    {"computed_style": [...]}   keep only those CSS props in every node
    {"attributes":    [...]}    keep only those attribute names
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence

from dimensions.schema.filter import FilterRule, FilterSpec


# ── selector parsing ─────────────────────────────────────────────────────────


# Attribute aliases — the canonical UIPath grammar uses ``testid`` to mean
# any of ``data-testid`` / ``data-test-id`` / ``data-test``; reuse that
# convention here so filter selectors stay readable.
_TESTID_ALIASES = ("data-testid", "data-test-id", "data-test")


_SELECTOR_RE = re.compile(
    r"^\s*"
    r"(?P<tag>[a-zA-Z][\w-]*|\*)?"
    r"(?P<id>#[\w-]+)?"
    r"(?P<classes>(?:\.[\w-]+)*)"
    r"(?P<attrs>(?:\[[^\]]+\])*)"
    r"\s*$"
)

_ATTR_RE = re.compile(r"\[([^=\]]+)(?:=([^\]]+))?\]")


def _parse_one(sel: str) -> "_SelectorMatcher":
    m = _SELECTOR_RE.match(sel)
    if not m:
        raise ValueError(f"invalid selector: {sel!r}")
    tag = m.group("tag")
    id_attr = m.group("id")[1:] if m.group("id") else None
    classes = [c for c in (m.group("classes") or "").split(".") if c]
    attrs: List[tuple] = []
    raw_attrs = m.group("attrs") or ""
    for am in _ATTR_RE.finditer(raw_attrs):
        attrs.append((am.group(1), am.group(2)))
    return _SelectorMatcher(
        tag=tag if tag and tag != "*" else None,
        id=id_attr,
        classes=tuple(classes),
        attrs=tuple(attrs),
    )


def _parse_group(selector: str) -> List["_SelectorMatcher"]:
    """`a, b, c` → list of matchers; node passes if any matcher matches."""
    return [_parse_one(part) for part in selector.split(",") if part.strip()]


class _SelectorMatcher:
    __slots__ = ("tag", "id", "classes", "attrs")

    def __init__(
        self,
        *,
        tag: Optional[str],
        id: Optional[str],
        classes: tuple,
        attrs: tuple,
    ) -> None:
        self.tag = (tag or "").lower() or None
        self.id = id
        self.classes = classes
        self.attrs = attrs

    def matches(self, node: Dict[str, Any]) -> bool:
        if self.tag and (node.get("tag") or "").lower() != self.tag:
            return False
        node_attrs = node.get("attributes") or {}
        if self.id and node_attrs.get("id") != self.id:
            return False
        if self.classes:
            node_classes = set(node.get("classes") or [])
            if not all(c in node_classes for c in self.classes):
                return False
        for attr_name, attr_value in self.attrs:
            present, actual = _read_attr(node_attrs, attr_name)
            if not present:
                return False
            if attr_value is not None and actual != attr_value:
                return False
        return True


def _read_attr(attrs: Dict[str, Any], name: str) -> tuple:
    """Read an attribute, expanding the ``testid`` alias."""
    if name == "testid":
        for alias in _TESTID_ALIASES:
            if alias in attrs:
                return True, attrs[alias]
        return False, None
    if name in attrs:
        return True, attrs[name]
    return False, None


# ── field whitelisting ──────────────────────────────────────────────────────


def _prune_fields(node: Dict[str, Any], fields: Sequence[str]) -> Dict[str, Any]:
    """Keep only the top-level / dotted fields in ``fields``. Empty
    list (or ``["*"]``) keeps every field unchanged.

    ``idx`` and ``parent`` are always preserved — they're required for
    walk integrity.
    """
    if not fields or "*" in fields:
        return dict(node)

    keep_top: Dict[str, set] = {}     # top-key → set of sub-keys to keep ({"*"} for all)
    for spec in fields:
        if "." in spec:
            top, sub = spec.split(".", 1)
            keep_top.setdefault(top, set()).add(sub)
        else:
            keep_top.setdefault(spec, set()).add("*")
    # Walk integrity
    keep_top.setdefault("idx", {"*"})
    keep_top.setdefault("parent", {"*"})

    out: Dict[str, Any] = {}
    for k, v in node.items():
        if k not in keep_top:
            continue
        sub_keys = keep_top[k]
        if "*" in sub_keys or not isinstance(v, dict):
            out[k] = v
        else:
            out[k] = {sk: sv for sk, sv in v.items() if sk in sub_keys}
    return out


def _restrict_values(
    node: Dict[str, Any], values: Dict[str, List[str]],
) -> Dict[str, Any]:
    """Restrict dict-valued fields to a whitelist of keys."""
    if not values:
        return node
    out = dict(node)
    for field_name, allowed_keys in values.items():
        v = out.get(field_name)
        if not isinstance(v, dict):
            continue
        out[field_name] = {k: v[k] for k in allowed_keys if k in v}
    return out


# ── PageState filtering ──────────────────────────────────────────────────────


def apply_filter(state, spec: Optional[FilterSpec]):
    """Return a new PageState with ``dom_walk`` filtered.

    Walk semantics:
      * empty ``keep`` → every node passes the keep check.
      * non-empty ``keep`` → node passes iff it matches at least one rule.
      * ``drop`` matches always remove (even when also kept).

    After tree pruning, surviving nodes have their fields restricted
    (per the matching rule's ``fields``), then value-whitelists run.

    ``idx`` / ``parent`` indexes are re-numbered so the output walk is
    self-consistent; the original parent index is followed transitively
    to find each surviving node's new parent.
    """
    if spec is None or spec.is_empty():
        return state

    keep_matchers = [
        (rule, _parse_group(rule.selector))
        for rule in spec.keep
    ]
    drop_matchers = [
        (rule, _parse_group(rule.selector))
        for rule in spec.drop
    ]

    walk = list(state.dom_walk or [])
    by_idx = {n.get("idx", i): n for i, n in enumerate(walk)}

    survivors_with_rule: Dict[int, Optional[FilterRule]] = {}
    for n in walk:
        idx = n.get("idx", -1)
        # Drop check first — wins.
        dropped = any(
            any(m.matches(n) for m in matchers)
            for _, matchers in drop_matchers
        )
        if dropped:
            continue
        if keep_matchers:
            matched_rule = None
            for rule, matchers in keep_matchers:
                if any(m.matches(n) for m in matchers):
                    matched_rule = rule
                    break
            if matched_rule is None:
                continue
            survivors_with_rule[idx] = matched_rule
        else:
            survivors_with_rule[idx] = None

    # Spec-level fields whitelist (applies to every survivor unless
    # a matching rule supplied its own override).
    spec_fields = list(spec.fields) if spec.fields else []

    # Re-parent: each surviving node's new parent is its closest
    # surviving ancestor (-1 if none).
    new_walk: List[Dict[str, Any]] = []
    old_to_new: Dict[int, int] = {}
    for n in walk:
        old_idx = n.get("idx", -1)
        if old_idx not in survivors_with_rule:
            continue
        # Build pruned node.
        rule = survivors_with_rule[old_idx]
        if rule is not None and rule.fields is not None:
            fields = rule.fields
        else:
            fields = spec_fields
        pruned = _prune_fields(n, fields)
        pruned = _restrict_values(pruned, spec.values)
        # Find new parent.
        old_parent = n.get("parent", -1)
        cursor = old_parent
        new_parent = -1
        seen: set = set()
        while cursor != -1 and cursor not in seen:
            seen.add(cursor)
            if cursor in old_to_new:
                new_parent = old_to_new[cursor]
                break
            parent_node = by_idx.get(cursor)
            cursor = parent_node.get("parent", -1) if parent_node else -1
        new_idx = len(new_walk)
        old_to_new[old_idx] = new_idx
        pruned["idx"] = new_idx
        pruned["parent"] = new_parent
        new_walk.append(pruned)

    return replace(state, dom_walk=new_walk)
