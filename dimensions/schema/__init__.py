"""Pydantic models for the snapshot envelope contract.

Per-dimension envelope variants live under `dimensions.kinds.<name>.schema`
(e.g. `dimensions.kinds.data.DataEnvelope`). The discriminated union and
its `TypeAdapter` live under `dimensions.schema.envelope` and are populated
once `dimensions.kinds` has been imported.

This package re-exports only the universal pieces (observation kinds and
the envelope base class). For per-kind types, import from the kind module
directly to keep import-order semantics simple.
"""

from dimensions.schema.envelope import _EnvelopeBase
from dimensions.schema.observation import (
    BooleanObservation,
    DistributionObservation,
    HistogramObservation,
    Observation,
    ObservationAdapter,
    RuleCheckObservation,
    ScalarObservation,
    SetObservation,
)

__all__ = [
    "BooleanObservation",
    "DistributionObservation",
    "HistogramObservation",
    "Observation",
    "ObservationAdapter",
    "RuleCheckObservation",
    "ScalarObservation",
    "SetObservation",
    "_EnvelopeBase",
]
