"""Scenario / Step validation — typed UIPath targets, resolve guard."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dimensions.testing.scenarios import Scenario
from dimensions.uipath import UIPath, format_uipath


# ── valid case ────────────────────────────────────────────────────────────


def _login_fixture() -> dict:
    return {
        "url": "https://fixture.test/login",
        "dom_walk": {
            "html>body>main>form[testid=login]>input[name=email]": {},
            "html>body>main>form[testid=login]>input[name=password]": {},
            "html>body>main>form[testid=login]>button[name=submit]": {
                "text": "Sign in"
            },
        },
    }


def test_valid_steps_load_and_targets_are_typed_uipath():
    sc = Scenario.model_validate({
        "name": "login_flow",
        "plugin": "visual",
        "fixture": _login_fixture(),
        "steps": [
            {"action": "type",
             "target": "html>body>main>form[testid=login]>input[name=email]",
             "value": "alice@example.com"},
            {"action": "click",
             "target": "html>body>main>form[testid=login]>button[name=submit]"},
        ],
    })
    assert all(isinstance(s.target, UIPath) for s in sc.steps)
    # Round-trip back to canonical string form.
    assert format_uipath(sc.steps[0].target).endswith("input[name=email]")


def test_step_without_target_is_allowed():
    sc = Scenario.model_validate({
        "name": "navigation",
        "plugin": "visual",
        "fixture": _login_fixture(),
        "steps": [{"action": "visit", "url": "https://fixture.test/login"}],
    })
    assert sc.steps[0].target is None


# ── invalid cases ─────────────────────────────────────────────────────────


def test_unresolvable_target_fails_at_load():
    with pytest.raises(ValidationError) as exc:
        Scenario.model_validate({
            "name": "bad_target",
            "plugin": "visual",
            "fixture": _login_fixture(),
            "steps": [{
                "action": "click",
                "target": "form[testid=nonexistent]>button",
            }],
        })
    assert "does not resolve" in str(exc.value)


def test_syntactically_invalid_target_fails_at_parse():
    with pytest.raises(ValidationError):
        Scenario.model_validate({
            "name": "bad_syntax",
            "plugin": "visual",
            "fixture": _login_fixture(),
            "steps": [{"action": "click", "target": "html>>>foo"}],
        })


def test_typo_in_testid_is_caught():
    """LLM-confabulation guard: a one-letter typo in a testid fails
    at load, not at run time."""
    with pytest.raises(ValidationError) as exc:
        Scenario.model_validate({
            "name": "typo_scenario",
            "plugin": "visual",
            "fixture": _login_fixture(),
            "steps": [{
                "action": "click",
                "target": "html>body>main>form[testid=loign]>button[name=submit]",
            }],
        })
    assert "does not resolve" in str(exc.value)


# ── stability surfacing ───────────────────────────────────────────────────


def test_target_stability_strong_for_testid_path():
    sc = Scenario.model_validate({
        "name": "stable",
        "plugin": "visual",
        "fixture": _login_fixture(),
        "steps": [{
            "action": "click",
            "target": "html>body>main>form[testid=login]>button[name=submit]",
        }],
    })
    assert sc.target_stability() == {0: "strong"}


# ── serialization round-trip ──────────────────────────────────────────────


# ── expect step execution ─────────────────────────────────────────────────


def test_expect_text_fires_on_mismatch():
    """A scenario whose expect_text disagrees with the fixture's text
    must fail at run, not silently pass."""
    import asyncio
    from dimensions.testing import run_scenario
    from plugins.visual import VisualPlugin

    sc = Scenario.model_validate({
        "name": "expect_mismatch",
        "plugin": "visual",
        "fixture": {
            "url": "https://fixture.test/x",
            "dom_walk": {
                "html>body>div[testid=greet]": {"text": "Hello"}
            },
        },
        "steps": [{
            "action": "expect_text",
            "target": "html>body>div[testid=greet]",
            "value": "Goodbye",
        }],
    })
    with pytest.raises(AssertionError) as exc:
        asyncio.run(run_scenario(sc, VisualPlugin))
    assert "expect_text" in str(exc.value)
    assert "Hello" in str(exc.value)
    assert "Goodbye" in str(exc.value)


def test_expect_visible_fires_when_hidden():
    import asyncio
    from dimensions.testing import run_scenario
    from plugins.visual import VisualPlugin

    sc = Scenario.model_validate({
        "name": "expect_hidden",
        "plugin": "visual",
        "fixture": {
            "url": "https://fixture.test/x",
            "dom_walk": {
                "html>body>div[testid=hidden]": {"visible": False}
            },
        },
        "steps": [{
            "action": "expect_visible",
            "target": "html>body>div[testid=hidden]",
        }],
    })
    with pytest.raises(AssertionError) as exc:
        asyncio.run(run_scenario(sc, VisualPlugin))
    assert "expect_visible" in str(exc.value)


def test_target_serializes_back_to_string():
    sc = Scenario.model_validate({
        "name": "serialize",
        "plugin": "visual",
        "fixture": _login_fixture(),
        "steps": [{
            "action": "click",
            "target": "html>body>main>form[testid=login]>button[name=submit]",
        }],
    })
    dumped = sc.model_dump(mode="json")
    assert isinstance(dumped["steps"][0]["target"], str)
    assert dumped["steps"][0]["target"].endswith("button[name=submit]")
