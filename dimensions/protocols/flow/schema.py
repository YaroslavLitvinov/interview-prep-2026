"""Pydantic schema for the flow "protocol".

A flow has no live system to observe — it's pure orchestration over
other scenarios. The envelope is still useful: it carries the
per-step pass/fail rollup, persisted progressively as the flow runs.
"""

from typing import List, Literal

from pydantic import BaseModel, ConfigDict

from dimensions.schema.envelope import _EnvelopeBase, register_envelope


class FlowSubject(BaseModel):
    """Subject schema for flow envelopes — the flow's identity + step refs."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["flow"]
    name: str
    steps: List[str]   # "<dim>/<scenario>" refs, in order


@register_envelope
class FlowEnvelope(_EnvelopeBase):
    """Envelope for a flow run — per-step rule_checks + overall rollup."""

    protocol: Literal["flow"]
    subject:  FlowSubject
    dimension_version: int = 1
