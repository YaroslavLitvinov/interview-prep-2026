"""Pydantic schema for the json_file InjectionProtocol.

Owns the envelope + subject shape produced by any JsonFileProtocol
implementation. A file on disk is read; structural observations are
emitted against its content.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from dimensions.schema.envelope import _EnvelopeBase, register_envelope


class FileSubject(BaseModel):
    """Subject schema for json_file captures — a file on disk."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["file"]
    path: str
    sha256: Optional[str] = None
    size_bytes: Optional[int] = None


@register_envelope
class JsonFileEnvelope(_EnvelopeBase):
    """Envelope variant for the json_file InjectionProtocol."""

    protocol: Literal["json_file"]
    subject: FileSubject
    dimension_version: int = 1
