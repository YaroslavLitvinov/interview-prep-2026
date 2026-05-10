"""Dimensions framework — observe, validate, compare, render.

Public surface: `Dimensions` is the single entry point. `Dimension` wraps a
`Plugin`. Backends are an internal detail; users never instantiate one.
"""

# Importing `dimensions.kinds` registers each per-dimension Pydantic schema
# with the discriminated envelope union. Must happen before any code path
# touches `EnvelopeAdapter`.
from dimensions import kinds  # noqa: F401

from dimensions.api import (
    CollectionContext,
    EnvelopeBuilder,
    Plugin,
)
from dimensions.dimension import Dimension
from dimensions.dimensions import Dimensions
from dimensions.validate import (
    SnapshotValidationError,
    get_envelope_json_schema,
    validate_envelope,
    validate_envelope_file,
)

__all__ = [
    "CollectionContext",
    "Dimension",
    "Dimensions",
    "EnvelopeBuilder",
    "Plugin",
    "SnapshotValidationError",
    "get_envelope_json_schema",
    "validate_envelope",
    "validate_envelope_file",
]
