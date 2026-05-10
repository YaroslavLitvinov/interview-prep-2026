"""pytest auto-discovery of Scenario JSON fixtures.

Hook into any project's pytest run by adding this directory to the
collection path (see `pytest_plugins` in the project's top-level
conftest, or a `conftest.py` import). Scenarios under
``tests/scenarios/<plugin>/*.json`` become parametrised pytest cases —
one per fixture file.
"""

from __future__ import annotations

import asyncio

import pytest

from dimensions.testing.scenarios import discover, run_scenario


# Plugin registry mapping plugin name → plugin class.
# Extended as new plugins arrive; visual is the only one in PR1.
def _plugin_class(name: str):
    if name == "visual":
        from plugins.visual import VisualPlugin
        return VisualPlugin
    raise pytest.UsageError(f"no plugin class registered for {name!r}")


@pytest.mark.parametrize(
    "scenario",
    discover(),
    ids=lambda s: f"{s.plugin}/{s.name}",
)
def test_scenario(scenario):
    plugin_cls = _plugin_class(scenario.plugin)
    asyncio.run(run_scenario(scenario, plugin_cls))
