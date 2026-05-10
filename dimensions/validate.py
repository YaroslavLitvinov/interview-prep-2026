"""Schema validation for envelopes.

Validation goes through the Pydantic models in `dimensions.schema`. The
exposed JSON Schema (in `dimensions/schema/_generated/`) is generated from
the same models, so the runtime check and the published contract stay
aligned by construction.
"""

import json
from pathlib import Path
from typing import Any, Dict, Tuple

from pydantic import ValidationError

from dimensions.schema.envelope import EnvelopeAdapter


_LEGACY_VERSION_KEY = "version"


class SnapshotValidationError(Exception):
    """Raised when an envelope fails schema validation."""


def migrate_envelope(envelope: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Rewrite a legacy single-``version`` envelope to the three-axis shape.

    Old snapshots had a single ``version: int`` field. The new model has
    three independent axes: ``envelope_version``, ``observation_schema_version``,
    ``dimension_version``. This migrator infers ``envelope_version`` from
    the legacy value and defaults the other two axes to ``1``.

    The defaulting is **lossy in one direction only** — old snapshots
    carried no notion of separate axes, so we can only infer "everything
    was at 1" for the unmoved fields. That assumption is safe today
    because no version has been bumped past 1 yet; revisit before any axis
    advances.

    Returns ``(new_envelope, did_migrate)``. If the envelope is already in
    the new shape, returns ``(envelope, False)`` unchanged.
    """
    if _LEGACY_VERSION_KEY not in envelope:
        return envelope, False
    new = dict(envelope)
    legacy = new.pop(_LEGACY_VERSION_KEY)
    new.setdefault(
        "envelope_version", legacy if isinstance(legacy, int) else 1
    )
    new.setdefault("observation_schema_version", 1)
    new.setdefault("dimension_version", 1)
    return new, True


def validate_envelope(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an envelope dict against the schema.

    Returns a normalized dict (Pydantic-roundtripped) on success.
    Raises SnapshotValidationError with a helpful message on failure.
    """
    try:
        validated = EnvelopeAdapter.validate_python(envelope)
    except ValidationError as e:
        raise SnapshotValidationError(_format_validation_error(e)) from e
    return EnvelopeAdapter.dump_python(validated, mode="json")


def validate_envelope_file(path: Path) -> Dict[str, Any]:
    """Validate a snapshot file. Returns normalized envelope on success."""
    path = Path(path)
    raw = json.loads(path.read_text())
    return validate_envelope(raw)


def is_valid(envelope: Dict[str, Any]) -> Tuple[bool, str]:
    """Non-raising variant — returns (ok, message)."""
    try:
        validate_envelope(envelope)
    except SnapshotValidationError as e:
        return False, str(e)
    return True, "ok"


def get_envelope_json_schema() -> Dict[str, Any]:
    """Return the JSON Schema (Draft 2020-12) generated from Pydantic models."""
    return EnvelopeAdapter.json_schema()


def _format_validation_error(e: ValidationError) -> str:
    parts = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"])
        msg = err["msg"]
        parts.append(f"  $.{loc}: {msg}")
    return "Envelope failed schema validation:\n" + "\n".join(parts)
