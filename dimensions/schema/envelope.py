"""Base envelope shape and the discriminated union over all dimension kinds.

The per-dimension envelope variants (DataEnvelope, VisualEnvelope, ...) live
in `dimensions.protocols.<name>.schema`. This module defines only the shared base
fields and assembles the union after the kind packages have been imported.

Import order matters: every per-kind Pydantic class must exist BEFORE the
discriminated union is built. `dimensions/__init__.py` imports
`dimensions.protocols` first, which in turn imports each kind's schema module.
"""

from typing import Annotated, List, Literal, Optional, Type, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from dimensions.schema.observation import Observation


class Provenance(BaseModel):
    """Origin marker for an envelope.

    Optional on every envelope — live captures leave it unset. Replay
    runs (``dimensions <dim> scenarios run``) stamp it with the
    scenario that produced the envelope so renderers can surface
    ``This came from scenario X`` without having to match URLs after
    the fact.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["scenario"] = Field(
        default="scenario",
        description="What produced this envelope. Today only `scenario`; "
                    "more kinds (replay-of-replay, llm-discovery, …) later.",
    )
    name: str = Field(..., description="Scenario name.")
    plugin: str = Field(..., description="Plugin the scenario targets.")
    path: Optional[str] = Field(
        default=None,
        description="Source file the scenario was loaded from (relative).",
    )


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
    provenance: Optional[Provenance] = Field(
        default=None,
        description="Origin marker (scenario replay, …). Unset on live captures.",
    )


# ── Discriminated union — built dynamically from registered envelopes ──────


_REGISTERED: List[Type[_EnvelopeBase]] = []
Envelope = None  # type: ignore[assignment]
EnvelopeAdapter: TypeAdapter = None  # type: ignore[assignment]


def register_envelope(cls: Type[_EnvelopeBase]) -> Type[_EnvelopeBase]:
    """Register an envelope subclass; rebuilds the discriminated union.

    Each per-protocol module decorates its envelope class with this at
    import time. New protocols (built-in or user extension) just import
    and the union extends — no hardcoded list to maintain.
    """
    if cls not in _REGISTERED:
        _REGISTERED.append(cls)
        _rebuild_adapter()
    return cls


def _rebuild_adapter() -> None:
    global Envelope, EnvelopeAdapter
    if not _REGISTERED:
        return
    if len(_REGISTERED) == 1:
        Envelope = _REGISTERED[0]
    else:
        Envelope = Annotated[
            Union[tuple(_REGISTERED)],            # type: ignore[arg-type]
            Field(discriminator="protocol"),
        ]
    EnvelopeAdapter = TypeAdapter(Envelope)


def _build_adapter() -> None:
    """Back-compat hook for the old kinds package. Imports each
    protocol module so its envelope class registers via the decorator,
    then ensures the adapter is built.
    """
    import dimensions.protocols  # noqa: F401
    _rebuild_adapter()
