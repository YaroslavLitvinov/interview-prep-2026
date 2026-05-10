"""Render targets — each consumes the IR (`ReportNode`) and emits a
specific format (markdown today; HTML / Allure / etc. later)."""

from dimensions.renderers.html import HtmlRenderer
from dimensions.renderers.markdown import MarkdownRenderer

__all__ = ["HtmlRenderer", "MarkdownRenderer"]
