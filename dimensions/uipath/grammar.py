"""UIPath grammar — Pydantic models, parser, and formatter.

Grammar (BNF)::

    UIPath  := segment ('>' segment)*
    segment := tag selector*
    tag     := lowercase_name
    selector := '#' simple_value                    # id shorthand
              | '[' attr_kind '=' attr_value ']'    # bracket selector
              | ':nth(' digit+ ')'                  # sibling disambiguation
    attr_kind  := 'testid' | 'id' | 'role' | 'name'
    attr_value := simple_value | quoted_value

Round-trip contract: ``parse(format_uipath(p)) == p`` for any well-formed
``UIPath`` produced by ``derive``. Pinned by tests.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import List, Tuple

from pydantic import BaseModel, ConfigDict


# ── enums + models ───────────────────────────────────────────────────────


class SelectorKind(str, Enum):
    """Selector priority order — also the canonicalisation precedence."""

    TESTID = "testid"
    ID = "id"
    ROLE = "role"
    NAME = "name"
    NTH = "nth"


class Selector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: SelectorKind
    value: str


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tag: str
    selectors: Tuple[Selector, ...] = ()


class UIPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    segments: Tuple[Segment, ...]


# ── escape rules ─────────────────────────────────────────────────────────


# A "simple" value is one that can appear unquoted in a bracket selector
# or after `#`. Anything else gets double-quoted with backslash escapes
# for `"` and `\`.
_SIMPLE_VALUE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")


def _is_simple_value(v: str) -> bool:
    return bool(v) and bool(_SIMPLE_VALUE_RE.match(v))


def _escape_quoted(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"')


def _format_value(v: str) -> str:
    if _is_simple_value(v):
        return v
    return f'"{_escape_quoted(v)}"'


# ── format ───────────────────────────────────────────────────────────────


def _format_segment(seg: Segment) -> str:
    out = seg.tag
    for sel in seg.selectors:
        if sel.kind == SelectorKind.NTH:
            out += f":nth({sel.value})"
        elif sel.kind == SelectorKind.ID and _is_simple_value(sel.value):
            out += f"#{sel.value}"
        else:
            out += f"[{sel.kind.value}={_format_value(sel.value)}]"
    return out


def format_uipath(p: UIPath) -> str:
    return ">".join(_format_segment(s) for s in p.segments)


# ── parse ────────────────────────────────────────────────────────────────


_TAG_RE = re.compile(r"^[a-z][a-z0-9_-]*", re.IGNORECASE)


class _ParseError(ValueError):
    pass


def parse(s: str) -> UIPath:
    """Parse a UIPath string into a structured model.

    Accepts both the canonical output of ``format_uipath`` and the
    backwards-compatible shape produced by the legacy ``_path_keys``
    function (``tag#id:nth(N)`` chains).
    """
    if s == "":
        return UIPath(segments=())
    return UIPath(segments=tuple(_parse_segment(part) for part in s.split(">")))


def _parse_segment(raw: str) -> Segment:
    raw = raw.strip()
    if not raw:
        raise _ParseError("empty segment")

    m = _TAG_RE.match(raw)
    if not m:
        raise _ParseError(f"segment must start with a tag: {raw!r}")
    tag = m.group(0)
    rest = raw[len(tag):]
    selectors: List[Selector] = []

    while rest:
        if rest.startswith("#"):
            # `#simple_value`
            sel, rest = _parse_id_shorthand(rest)
            selectors.append(sel)
        elif rest.startswith("["):
            sel, rest = _parse_bracket_selector(rest)
            selectors.append(sel)
        elif rest.startswith(":nth("):
            sel, rest = _parse_nth(rest)
            selectors.append(sel)
        else:
            raise _ParseError(f"unexpected token in segment {raw!r}: {rest!r}")
    return Segment(tag=tag, selectors=tuple(selectors))


def _parse_id_shorthand(rest: str) -> Tuple[Selector, str]:
    # Consume contiguous run of [A-Za-z0-9_-] after the `#`.
    m = re.match(r"^#([A-Za-z_][A-Za-z0-9_\-]*)", rest)
    if not m:
        raise _ParseError(f"invalid id shorthand: {rest!r}")
    return Selector(kind=SelectorKind.ID, value=m.group(1)), rest[m.end():]


def _parse_bracket_selector(rest: str) -> Tuple[Selector, str]:
    # `[kind=value]` with optional quoted value.
    m = re.match(r"^\[(testid|id|role|name)=", rest)
    if not m:
        raise _ParseError(f"invalid bracket selector: {rest!r}")
    kind = SelectorKind(m.group(1))
    after = rest[m.end():]
    if after.startswith('"'):
        # quoted: scan until unescaped `"`
        value, after = _consume_quoted(after)
    else:
        # simple value: up to `]`
        end = after.find("]")
        if end < 0:
            raise _ParseError(f"unterminated bracket selector: {rest!r}")
        value = after[:end]
        after = after[end:]
    if not after.startswith("]"):
        raise _ParseError(f"unterminated bracket selector: {rest!r}")
    return Selector(kind=kind, value=value), after[1:]


def _consume_quoted(s: str) -> Tuple[str, str]:
    # s starts with `"`; consume until matching unescaped `"`.
    assert s.startswith('"')
    out: List[str] = []
    i = 1
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append(s[i + 1])
            i += 2
            continue
        if c == '"':
            return "".join(out), s[i + 1:]
        out.append(c)
        i += 1
    raise _ParseError(f"unterminated quoted value: {s!r}")


def _parse_nth(rest: str) -> Tuple[Selector, str]:
    m = re.match(r"^:nth\((\d+)\)", rest)
    if not m:
        raise _ParseError(f"invalid :nth(): {rest!r}")
    return Selector(kind=SelectorKind.NTH, value=m.group(1)), rest[m.end():]
