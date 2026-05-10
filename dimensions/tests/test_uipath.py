"""UIPath grammar contracts — round-trip, resolve, class-rename invariance."""

from __future__ import annotations

from dimensions.uipath import (
    SelectorKind,
    UIPath,
    derive_all,
    format_uipath,
    from_node,
    parse,
    resolve,
    stability,
    Stability,
)


# ── basic round-trip ─────────────────────────────────────────────────────


def test_parse_format_round_trip_legacy_shape():
    s = "html>body>div#root>div:nth(2)>span"
    assert format_uipath(parse(s)) == s


def test_parse_format_round_trip_rich_shape():
    s = "main>section[testid=users-form]>form>input[name=email]"
    assert format_uipath(parse(s)) == s


def test_parse_format_round_trip_quoted_value():
    s = 'button[name="Save & quit"]'
    assert format_uipath(parse(s)) == s


def test_empty_path():
    assert parse("").segments == ()
    assert format_uipath(UIPath(segments=())) == ""


# ── selector priority ─────────────────────────────────────────────────────


def _walk(*nodes):
    return list(nodes)


def test_testid_wins_over_id():
    walk = _walk(
        {"idx": 0, "parent": -1, "tag": "html", "attributes": {}},
        {"idx": 1, "parent": 0, "tag": "section", "id": "old",
         "attributes": {"data-testid": "users-form"}},
    )
    paths = derive_all(walk)
    assert format_uipath(paths[1]) == "html>section[testid=users-form]"


def test_role_plus_name_when_no_id():
    walk = _walk(
        {"idx": 0, "parent": -1, "tag": "html", "attributes": {}},
        {"idx": 1, "parent": 0, "tag": "button",
         "attributes": {"role": "button", "aria-label": "Submit"}},
    )
    paths = derive_all(walk)
    assert format_uipath(paths[1]) == 'html>button[role=button][name=Submit]'


def test_pure_structural_falls_back_to_nth():
    walk = _walk(
        {"idx": 0, "parent": -1, "tag": "html", "attributes": {}},
        {"idx": 1, "parent": 0, "tag": "div", "attributes": {}},
        {"idx": 2, "parent": 0, "tag": "div", "attributes": {}},
    )
    paths = derive_all(walk)
    assert format_uipath(paths[1]) == "html>div:nth(1)"
    assert format_uipath(paths[2]) == "html>div:nth(2)"


# ── resolve-after-derive contract ─────────────────────────────────────────


def test_resolve_after_derive_returns_same_node():
    walk = _walk(
        {"idx": 0, "parent": -1, "tag": "html", "attributes": {}},
        {"idx": 1, "parent": 0, "tag": "body", "attributes": {}},
        {"idx": 2, "parent": 1, "tag": "div", "id": "root", "attributes": {}},
        {"idx": 3, "parent": 2, "tag": "section",
         "attributes": {"data-testid": "main"}},
    )
    target = walk[3]
    p = from_node(target, walk)
    assert resolve(p, walk) is target


def test_resolve_unknown_returns_none():
    walk = _walk(
        {"idx": 0, "parent": -1, "tag": "html", "attributes": {}},
    )
    p = parse("html>section[testid=nope]")
    assert resolve(p, walk) is None


# ── class-rename invariance ───────────────────────────────────────────────


def test_class_rename_does_not_change_path():
    """Class churn (Streamlit hash classes etc) must not alter UIPath.
    This is the central contract of the matching algorithm."""
    walk_a = _walk(
        {"idx": 0, "parent": -1, "tag": "html", "attributes": {},
         "classes": ["a-old", "stApp"]},
        {"idx": 1, "parent": 0, "tag": "section", "id": "main",
         "attributes": {}, "classes": ["e1abc"]},
    )
    walk_b = _walk(
        {"idx": 0, "parent": -1, "tag": "html", "attributes": {},
         "classes": ["a-new", "stApp"]},
        {"idx": 1, "parent": 0, "tag": "section", "id": "main",
         "attributes": {}, "classes": ["e2xyz"]},
    )
    pa = derive_all(walk_a)
    pb = derive_all(walk_b)
    assert {format_uipath(p) for p in pa.values()} == {
        format_uipath(p) for p in pb.values()
    }


# ── backwards-compat: legacy _path_keys output identical for legacy walks ──


def test_path_keys_back_compat():
    """A walk lacking testid/role/name produces identical path keys to
    the original `_path_keys_legacy` implementation."""
    from dimensions.diff_render import _path_keys, _path_keys_legacy
    walk = _walk(
        {"idx": 0, "parent": -1, "tag": "html", "attributes": {}},
        {"idx": 1, "parent": 0, "tag": "body", "attributes": {}},
        {"idx": 2, "parent": 1, "tag": "div", "id": "root", "attributes": {}},
        {"idx": 3, "parent": 2, "tag": "div", "attributes": {}},
        {"idx": 4, "parent": 2, "tag": "div", "attributes": {}},
        {"idx": 5, "parent": 4, "tag": "span", "attributes": {}},
    )
    assert _path_keys(walk) == _path_keys_legacy(walk)


# ── stability scoring ─────────────────────────────────────────────────────


def test_stability_strong_with_testid():
    p = parse("main>section[testid=foo]>input")
    assert stability(p) == Stability.STRONG


def test_stability_strong_with_id():
    p = parse("main>section#main>div")
    assert stability(p) == Stability.STRONG


def test_stability_medium_with_role_name():
    p = parse("main>button[role=button][name=Save]")
    assert stability(p) == Stability.MEDIUM


def test_stability_weak_pure_structural():
    p = parse("html>body>div:nth(2)>div")
    assert stability(p) == Stability.WEAK
