"""Flow "protocol" — orchestration over other scenarios.

No real-world observation; the flow envelope records which unit
scenarios ran, in what order, with what outcome. Persisted
progressively (one write per step transition) so reports stay live.
"""

from dimensions.protocols.flow.schema import FlowEnvelope, FlowSubject

__all__ = ["FlowEnvelope", "FlowSubject"]
