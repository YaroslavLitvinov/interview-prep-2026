"""Pydantic schema for the browser InjectionProtocol.

Owns the envelope + subject shape produced by any BrowserProtocol
implementation (real Playwright, fixture replay, future Selenium…).
Cross-language plugin authors validate against the JSON Schema
generated from this module.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from dimensions.schema.envelope import _EnvelopeBase, register_envelope


class UrlSubject(BaseModel):
    """Subject schema for browser captures — a renderable URL."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["url"]
    url: str
    viewport: Optional[dict] = None
    browser: Optional[str] = None


@register_envelope
class BrowserEnvelope(_EnvelopeBase):
    """Envelope variant for the browser InjectionProtocol.

    ``dimension_version`` is owned by this class; bump independently
    of other protocols' versions when the browser envelope shape
    changes.
    """

    protocol: Literal["browser"]
    subject: UrlSubject
    dimension_version: int = 1
