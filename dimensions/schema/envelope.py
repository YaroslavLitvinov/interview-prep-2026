"""Base envelope shape and the discriminated union over all dimension kinds.

The per-dimension envelope variants (DataEnvelope, VisualEnvelope, ...) live
in `dimensions.kinds.<name>.schema`. This module defines only the shared base
fields and assembles the union after the kind packages have been imported.

Import order matters: every per-kind Pydantic class must exist BEFORE the
discriminated union is built. `dimensions/__init__.py` imports
`dimensions.kinds` first, which in turn imports each kind's schema module.
"""

from typing import Annotated, List, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from dimensions.schema.observation import Observation


class _EnvelopeBase(BaseModel):
    """Fields shared by every envelope variant.

    Versioning has three independent axes. They evolve at different rates:

    - ``envelope_version``      — top-level envelope shape (e.g., adding
                                  a new envelope-level field, restructuring
                                  ``subject`` discriminator).
    - ``observation_schema_version`` — observation kind catalog and shape
                                  (e.g., adding a new kind, changing a
                                  kind's required fields).
    - ``dimension_version``     — per-dimension shape (e.g., adding
                                  ``mtime`` to ``FileSubject``, requiring a
                                  new observation id from Data plugins).
                                  Each per-kind subclass declares its own
                                  default; a bump in the Data dimension
                                  does not move Visual.
    """

    model_config = ConfigDict(extra="forbid")

    envelope_version: int = Field(
        default=2,
        description=(
            "Envelope shape version. Bumps when shared top-level fields "
            "change. v2 added `envelope_name` for multi-envelope captures."
        ),
    )
    observation_schema_version: int = Field(
        default=2,
        description=(
            "Observation kind catalog version. Bumps when an observation kind "
            "is added, removed, or its shape changes. v2 added the `payload` "
            "kind for arbitrary structured data."
        ),
    )
    envelope_name: str = Field(
        default="main",
        description=(
            "Stable key for this envelope within its (dimension, label). "
            "Plugins emit multiple envelopes per `collect()` call (e.g., one "
            "per source file or per URL × artifact-type); the name keeps "
            "them addressable. Default `main` for single-envelope plugins."
        ),
    )
    # No default on ``_EnvelopeBase`` — each kind subclass provides its own,
    # so Data can ship at v3 while Visual stays at v1 without dragging the
    # other along.
    dimension_version: int = Field(
        ...,
        description="Per-dimension shape version (set by the kind subclass).",
    )

    dimension: str
    captured_at: str = Field(..., description="ISO-8601 UTC timestamp.")
    observations: List[Observation]


# ── Discriminated union — assembled lazily after kinds register ─────────────

# Sentinels populated by `_build_adapter()` below. They start as None so
# importing this module does not eagerly drag in every kind.
Envelope = None  # type: ignore[assignment]
EnvelopeAdapter: TypeAdapter = None  # type: ignore[assignment]


def _build_adapter() -> None:
    """Construct the discriminated union over registered kinds.

    Called once, after all `dimensions.kinds.*.schema` modules have been
    imported (via `dimensions.kinds.__init__`). Idempotent.
    """
    global Envelope, EnvelopeAdapter
    if EnvelopeAdapter is not None:
        return

    from dimensions.kinds.data.schema import DataEnvelope
    from dimensions.kinds.visual.schema import VisualEnvelope

    Envelope = Annotated[
        Union[DataEnvelope, VisualEnvelope],
        Field(discriminator="category"),
    ]
    EnvelopeAdapter = TypeAdapter(Envelope)
