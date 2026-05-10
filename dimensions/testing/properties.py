"""Generic per-envelope properties the framework promises and asserts.

If any of these fail, the framework itself just lied — every plugin's
tests fail loudly, not just the one whose scenario tripped the wire.
"""

from __future__ import annotations

from typing import Any, Dict, List


def assert_generic(envelopes: List[Dict[str, Any]]) -> None:
    """Assert every framework-level invariant on each envelope."""
    for env in envelopes:
        _assert_entity_ids_unique(env)
        _assert_entity_ids_present(env)


def _assert_entity_ids_unique(env: Dict[str, Any]) -> None:
    ids = [
        o["entity_id"] for o in env.get("observations", [])
        if "entity_id" in o
    ]
    if len(ids) != len(set(ids)):
        raise AssertionError(
            f"entity_ids not unique in envelope "
            f"{env.get('envelope_name')!r}: {ids}"
        )


def _assert_entity_ids_present(env: Dict[str, Any]) -> None:
    missing = [
        o.get("id", "?") for o in env.get("observations", [])
        if "entity_id" not in o
    ]
    if missing:
        raise AssertionError(
            f"observations missing entity_id in envelope "
            f"{env.get('envelope_name')!r}: {missing}"
        )


# ── per-scenario expectations ─────────────────────────────────────────────


def assert_expectations(
    envelopes: List[Dict[str, Any]],
    expectations: Dict[str, Any],
) -> None:
    """Apply scenario-specific expectations to the envelope set.

    Supported keys:
      * ``envelopes``                 — list of envelope_name's that must exist
      * ``observations_must_include`` — list of obs ids that must appear (any envelope)
      * ``observations_must_not_include`` — list of obs ids that must not appear
    """
    if not expectations:
        return

    if "envelopes" in expectations:
        names = {e.get("envelope_name") for e in envelopes}
        for required in expectations["envelopes"]:
            if required not in names:
                raise AssertionError(
                    f"expected envelope {required!r} not produced; "
                    f"got {sorted(n for n in names if n)}"
                )

    if "observations_must_include" in expectations:
        all_ids = _all_observation_ids(envelopes)
        for required in expectations["observations_must_include"]:
            if required not in all_ids:
                raise AssertionError(
                    f"expected observation id {required!r} missing; "
                    f"got {sorted(all_ids)}"
                )

    if "observations_must_not_include" in expectations:
        all_ids = _all_observation_ids(envelopes)
        for forbidden in expectations["observations_must_not_include"]:
            if forbidden in all_ids:
                raise AssertionError(
                    f"observation id {forbidden!r} should not appear; "
                    f"the snapshot contains it"
                )


def _all_observation_ids(envelopes: List[Dict[str, Any]]) -> set:
    out = set()
    for env in envelopes:
        for obs in env.get("observations", []):
            if "id" in obs:
                out.add(obs["id"])
    return out
