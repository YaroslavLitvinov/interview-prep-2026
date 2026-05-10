"""Per-dimension framework modules.

Each canonical dimension owns a subpackage here with its Pydantic schema,
collection primitives, and a reference plugin (for inspiration only — the
project's own plugin in `/workspace/plugins/` is the canonical one).

Importing this package registers every kind's schema with the discriminated
envelope union by side-effect, then builds the EnvelopeAdapter. After this
import completes, `dimensions.schema.envelope.EnvelopeAdapter` is ready.
"""

from dimensions.kinds import data, visual
from dimensions.schema.envelope import _build_adapter

# Register every kind's Pydantic class with the discriminated union.
_build_adapter()


KIND_REGISTRY = {
    "data": {
        "envelope_cls": data.DataEnvelope,
        "subject_cls": data.FileSubject,
        "module": data,
    },
    "visual": {
        "envelope_cls": visual.VisualEnvelope,
        "subject_cls": visual.UrlSubject,
        "module": visual,
    },
}


__all__ = ["data", "visual", "KIND_REGISTRY"]
