"""Pydantic schema for the Visual dimension.

Owns the per-dimension shape: a Visual envelope wraps observations of a
URL rendered in a browser. Cross-language plugin authors validate against
the JSON Schema generated from this module.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from dimensions.schema.envelope import _EnvelopeBase


class UrlSubject(BaseModel):
    """Subject schema for the Visual dimension — a renderable URL."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["url"]
    url: str
    viewport: Optional[dict] = None
    browser: Optional[str] = None


class VisualEnvelope(_EnvelopeBase):
    """Envelope variant for the Visual dimension.

    ``dimension_version`` is owned by this class. Bump it independently of
    the Data dimension's version when Visual's shape changes.
    """

    category: Literal["visual"]
    subject: UrlSubject
    dimension_version: int = 1
