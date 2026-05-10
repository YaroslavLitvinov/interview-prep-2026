"""Pydantic schema for the Data dimension.

Owns the per-dimension shape: a Data envelope wraps observations of a
file-on-disk subject. Cross-language plugin authors validate against the
JSON Schema generated from this module.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from dimensions.schema.envelope import _EnvelopeBase


class FileSubject(BaseModel):
    """Subject schema for the Data dimension — a file on disk."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["file"]
    path: str
    sha256: Optional[str] = None
    size_bytes: Optional[int] = None


class DataEnvelope(_EnvelopeBase):
    """Envelope variant for the Data dimension.

    ``dimension_version`` is owned by this class. Bump it whenever the
    Data envelope shape changes (e.g., FileSubject gains a field, or a
    new observation id becomes required of every Data plugin). It moves
    independently of the Visual or any other dimension's version.
    """

    category: Literal["data"]
    subject: FileSubject
    dimension_version: int = 1
