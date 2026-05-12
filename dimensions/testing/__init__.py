"""Plugin self-testing: scenarios + URL substitution + test evaluation.

Scenarios are live-driven: a URL is loaded through the plugin's real
protocol, then ``tests`` declarations are evaluated against the
captured DOM walk.

Public surface:

    Scenario / discover()       — Pydantic model + on-disk discovery
    resolve_scenario_urls()     — ${name} substitution against config.urls
    evaluate_tests()            — run test assertions against captured envelopes
    UnresolvedScenarioVar       — raised when ${name} isn't in the URL map
    ScenarioCollision           — raised when two scenarios share (plugin, name)
"""

from dimensions.testing.scenarios import (
    Scenario,
    ScenarioCollision,
    UnresolvedScenarioVar,
    discover,
    evaluate_tests,
    resolve_scenario_urls,
)

__all__ = [
    "Scenario",
    "ScenarioCollision",
    "UnresolvedScenarioVar",
    "discover",
    "evaluate_tests",
    "resolve_scenario_urls",
]
