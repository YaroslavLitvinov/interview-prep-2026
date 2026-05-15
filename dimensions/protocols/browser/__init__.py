"""Browser InjectionProtocol — schema, primitives, real + fixture impls."""

from dimensions.protocols.browser.injection import (
    BrowserProtocol,
    PageState,
    PlaywrightBrowserProtocol,
    pixel_diff,
)
from dimensions.protocols.browser.primitives import (
    DEFAULT_TIMEOUT_MS,
    DEFAULT_VIEWPORT,
    emit_screenshot,
    emit_tree,
    url_subject_dict,
)
from dimensions.protocols.browser.filter import apply_filter
from dimensions.protocols.browser.schema import BrowserEnvelope, UrlSubject

__all__ = [
    "BrowserEnvelope",
    "BrowserProtocol",
    "DEFAULT_TIMEOUT_MS",
    "DEFAULT_VIEWPORT",
    "PageState",
    "PlaywrightBrowserProtocol",
    "UrlSubject",
    "apply_filter",
    "emit_screenshot",
    "emit_tree",
    "pixel_diff",
    "url_subject_dict",
]
