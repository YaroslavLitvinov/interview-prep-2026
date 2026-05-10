"""Plugin self-testing: fixture protocols, scenarios, generic properties.

Plugins are exercised the same way real captures exercise them — through
their `InjectionProtocol` seam — except the protocol is replaced by a
fixture replay that returns pre-recorded state. Generic properties then
assert the framework's universal contracts on the produced envelopes.

Public surface:

    Scenario / Step          — Pydantic models for a fixture + steps + expectations
    discover()                — find scenarios on disk
    run_scenario()            — execute one scenario through a real plugin
    assert_generic()          — assert framework-level invariants on envelopes
    FixtureBrowserProtocol    — replay a PageState
    make_fixture_protocol()   — pick the right fixture protocol for a Scenario
"""

from dimensions.testing.protocols import (
    FixtureBrowserProtocol,
    make_fixture_protocol,
    normalize_dom_walk,
)
from dimensions.testing.scenarios import (
    Scenario,
    Step,
    discover,
    run_scenario,
)
from dimensions.testing.properties import (
    assert_generic,
    assert_expectations,
)

__all__ = [
    "FixtureBrowserProtocol",
    "Scenario",
    "Step",
    "assert_expectations",
    "assert_generic",
    "discover",
    "make_fixture_protocol",
    "normalize_dom_walk",
    "run_scenario",
]
