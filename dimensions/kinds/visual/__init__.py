"""Visual dimension — schema, primitives, and browser injection protocols."""

from dimensions.kinds.visual.injection import (
    BrowserProtocol,
    ELEMENT_COLUMNS,
    INTERACTIVE_COLUMNS,
    PageState,
    PlaywrightBrowserProtocol,
    pixel_diff,
)
from dimensions.kinds.visual.primitives import (
    DEFAULT_TIMEOUT_MS,
    DEFAULT_VIEWPORT,
    emit_screenshot,
    emit_tree,
    url_subject_dict,
)
from dimensions.kinds.visual.schema import UrlSubject, VisualEnvelope

__all__ = [
    "BrowserProtocol",
    "DEFAULT_TIMEOUT_MS",
    "DEFAULT_VIEWPORT",
    "ELEMENT_COLUMNS",
    "INTERACTIVE_COLUMNS",
    "PageState",
    "PlaywrightBrowserProtocol",
    "UrlSubject",
    "VisualEnvelope",
    "emit_screenshot",
    "emit_tree",
    "pixel_diff",
    "url_subject_dict",
]
