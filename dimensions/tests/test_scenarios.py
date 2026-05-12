"""Scenario model + evaluator unit tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dimensions.testing.scenarios import (
    Scenario, evaluate_tests, resolve_scenario_urls,
    UnresolvedScenarioVar,
)


# ── parsing ────────────────────────────────────────────────────────────────


def test_minimal_scenario_parses():
    sc = Scenario.model_validate({
        "name":   "welcome",
        "plugin": "visual",
        "url":    "https://example.test/",
        "tests":  {
            "header_check": {
                "html>body>h1[testid=stHeading]": {"text": "Welcome"}
            }
        },
    })
    assert sc.name == "welcome"
    assert sc.url == "https://example.test/"
    assert "header_check" in sc.tests


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        Scenario.model_validate({
            "name": "x", "plugin": "visual", "url": "x",
            "fixture": {}, "tests": {},
        })


def test_url_required():
    with pytest.raises(ValidationError):
        Scenario.model_validate({"name": "x", "plugin": "visual", "tests": {}})


# ── URL substitution ───────────────────────────────────────────────────────


def test_url_substitution():
    sc = Scenario.model_validate({
        "name": "x", "plugin": "visual",
        "url": "${home}/page", "tests": {},
    })
    out = resolve_scenario_urls(sc, {"home": "http://localhost:8501"})
    assert out.url == "http://localhost:8501/page"


def test_unknown_var_fails():
    sc = Scenario.model_validate({
        "name": "x", "plugin": "visual", "url": "${nope}", "tests": {},
    })
    with pytest.raises(UnresolvedScenarioVar):
        resolve_scenario_urls(sc, {"home": "http://x"})


# ── evaluator ──────────────────────────────────────────────────────────────


def _fake_envelope_with_walk(walk_root):
    """Build an envelope dict carrying a dom_tree payload."""
    return {
        "envelope_name": "main.tree",
        "observations": [{
            "id":             "page.dom_tree",
            "kind":           "payload",
            "payload_schema": "dom_tree",
            "data":           {"root": walk_root},
        }],
    }


def test_evaluate_pass():
    sc = Scenario.model_validate({
        "name": "x", "plugin": "visual", "url": "http://x",
        "tests": {
            "t1": {"html>body>div[testid=greet]": {"text": "Hello"}},
        },
    })
    tree = {"tag": "html", "children": [
        {"tag": "body", "children": [
            {"tag": "div", "attributes": {"data-testid": "greet"},
             "text": "Hello", "children": []},
        ]},
    ]}
    result = evaluate_tests(sc, [_fake_envelope_with_walk(tree)])
    assert result["passed"] is True
    assert result["tests"][0]["passed"] is True


def test_evaluate_text_mismatch():
    sc = Scenario.model_validate({
        "name": "x", "plugin": "visual", "url": "http://x",
        "tests": {
            "t1": {"html>body>div[testid=greet]": {"text": "Goodbye"}},
        },
    })
    tree = {"tag": "html", "children": [
        {"tag": "body", "children": [
            {"tag": "div", "attributes": {"data-testid": "greet"},
             "text": "Hello", "children": []},
        ]},
    ]}
    result = evaluate_tests(sc, [_fake_envelope_with_walk(tree)])
    assert result["passed"] is False
    assert any("Hello" in v and "Goodbye" in v for v in result["violations"])


def test_evaluate_uipath_not_found():
    sc = Scenario.model_validate({
        "name": "x", "plugin": "visual", "url": "http://x",
        "tests": {
            "t1": {"html>body>div[testid=missing]": {"visible": True}},
        },
    })
    tree = {"tag": "html", "children": [
        {"tag": "body", "children": []}
    ]}
    result = evaluate_tests(sc, [_fake_envelope_with_walk(tree)])
    assert result["passed"] is False
    assert any("not found" in v for v in result["violations"])
