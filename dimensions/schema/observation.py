"""Pydantic models for the six observation kinds.

Every plugin emits a list of observations. Each observation is one of:
  scalar | boolean | rule_check | set | distribution | histogram

These models are the canonical contract. JSON Schema generated from them
is what cross-language plugin authors validate against.
"""

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class ObservationCommon(BaseModel):
    """Fields shared by every observation kind."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Stable identifier for the observation.")
    label: str = Field(..., description="Human-readable label.")
    entity_id: Optional[str] = Field(
        default=None,
        description=(
            "Content-derived stable entity id assigned by the framework. "
            "Comments and resolutions anchor to this; survives recapture."
        ),
    )
    required: bool = Field(
        default=False,
        description=(
            "Whether this observation is load-bearing for the snapshot's "
            "overall pass/fail. Required observations gate the snapshot; "
            "informational ones do not. Default False (informational)."
        ),
    )


class ScalarObservation(ObservationCommon):
    """A single named value (count, latency, size, named string, etc.)."""

    kind: Literal["scalar"]
    value: Any
    unit: Optional[str] = None


class BooleanObservation(ObservationCommon):
    """A binary property (passed/failed, present/missing)."""

    kind: Literal["boolean"]
    value: bool


class RuleCheckObservation(ObservationCommon):
    """A schema/pattern/invariant rule applied to N items."""

    kind: Literal["rule_check"]
    passed: bool
    violations_count: int = 0
    violations_sample: List[Any] = Field(default_factory=list)
    checked_count: Optional[int] = None


class SetObservation(ObservationCommon):
    """An unordered, deduplicated collection (inventory)."""

    kind: Literal["set"]
    items: List[str]


class DistributionObservation(ObservationCommon):
    """A keyed count map (e.g., items per category)."""

    kind: Literal["distribution"]
    buckets: Dict[str, int]


class HistogramItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    count: int


class HistogramObservation(ObservationCommon):
    """A frequency table; only the top-N items are kept."""

    kind: Literal["histogram"]
    total: int
    unique: int
    top_n: List[HistogramItem]


class PayloadObservation(ObservationCommon):
    """A structured payload of arbitrary shape.

    Used for rich data the fixed-shape kinds cannot carry — full DOM,
    per-element layout/computed-style tables, accessibility trees,
    screenshots (as base64), comparison results, and so on. The
    ``payload_schema`` field names the shape of ``data``; the framework
    dispatches diff and render on this discriminator. Unknown
    ``payload_schema`` values render as a generic JSON dump and diff
    structurally.
    """

    kind: Literal["payload"]
    payload_schema: str = Field(
        ...,
        description=(
            "Discriminator naming the shape of `data`. Recognised values "
            "('dom_tree', 'screenshot', 'comparison') get first-class "
            "diff/render; unknown values fall back to a generic JSON dump."
        ),
    )
    data: Any = Field(
        default=None,
        description="Schema-specific payload — opaque to the framework.",
    )


# Discriminated union over the seven kinds
Observation = Annotated[
    Union[
        ScalarObservation,
        BooleanObservation,
        RuleCheckObservation,
        SetObservation,
        DistributionObservation,
        HistogramObservation,
        PayloadObservation,
    ],
    Field(discriminator="kind"),
]

ObservationAdapter = TypeAdapter(Observation)
