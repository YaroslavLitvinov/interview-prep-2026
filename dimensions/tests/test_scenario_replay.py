"""Parse-only smoke tests for every Scenario JSON under the configured roots.

The CLI command ``dimensions <dim> capture <label>`` drives Playwright
and evaluates ``tests`` against the live page — that's the integration
path. This file's job is much smaller: ensure every committed scenario
parses cleanly, references a registered plugin, and has all its
``${name}`` URL placeholders satisfied by ``config.urls``.

If the live capture fails (app down, Chromium missing), that's an
operational concern surfaced by the CLI — not something pytest tries
to reproduce.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pytest

from dimensions.config import Config, DEFAULT_CONFIG_NAME
from dimensions.testing import (
    Scenario, UnresolvedScenarioVar, discover, resolve_scenario_urls,
)


def _config() -> Config:
    path = Path(DEFAULT_CONFIG_NAME)
    return Config.from_file(path) if path.exists() else Config()


_CONFIG = _config()
_PLUGIN_CLASSES: Dict[str, type] = _CONFIG.plugin_classes()
_SCENARIOS: List[Scenario] = discover(roots=_CONFIG.scenario_roots)


@pytest.mark.parametrize(
    "scenario",
    _SCENARIOS,
    ids=lambda s: f"{s.plugin}/{s.name}",
)
def test_scenario_validates(scenario: Scenario) -> None:
    # Plugin must be registered.
    if scenario.plugin not in _PLUGIN_CLASSES:
        raise pytest.UsageError(
            f"scenario {scenario.name!r} references plugin "
            f"{scenario.plugin!r}, not registered in "
            f"{DEFAULT_CONFIG_NAME}. Known: {sorted(_PLUGIN_CLASSES)}"
        )
    # Every ${name} placeholder must resolve.
    try:
        resolve_scenario_urls(scenario, _CONFIG.plugin_urls(scenario.plugin))
    except UnresolvedScenarioVar as exc:
        raise AssertionError(str(exc)) from exc
    # Every test entry must use a parseable UIPath (the model only
    # validates the dict shape; UIPath syntax is checked here).
    from dimensions.uipath import parse as _parse
    for test_name, assertions in (scenario.tests or {}).items():
        for uipath_str in assertions:
            try:
                _parse(uipath_str)
            except Exception as exc:  # noqa: BLE001
                raise AssertionError(
                    f"test {test_name!r}: invalid UIPath {uipath_str!r}: {exc}"
                ) from exc
