"""Public render entry points.

Both ``render_envelope_markdown`` and ``render_comparison_markdown`` are
thin wrappers over a two-stage pipeline:

  envelope/changes ─► RenderSchema ─► ReportNode IR ─► Renderer ─► output

Today only `MarkdownRenderer` is wired up; tomorrow's HTML / Allure /
etc. renderers consume the same IR. Per-dimension overrides are an
optional ``schema=`` kwarg accepting any subclass of `BaseRenderSchema`.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from dimensions.render_schema import BaseRenderSchema
from dimensions.renderers.markdown import MarkdownRenderer


def render_envelope_markdown(
    envelope: Dict[str, Any],
    *,
    asset_loader: Optional[Callable[[str], bytes]] = None,
    inline_assets: bool = True,
    schema: Optional[BaseRenderSchema] = None,
) -> str:
    """Render an envelope as Markdown via the IR pipeline.

    Asset handling for screenshot payloads:

    - ``inline_assets=True`` (default): screenshots embed as base64
      data URLs via ``asset_loader`` — markdown is self-contained.
    - ``inline_assets=False``: screenshots use the relative ``ref``
      path (``assets/<sha>.<ext>``). Smaller markdown; the file must
      live next to the snapshot's ``assets/`` directory.

    ``schema`` (optional): a `BaseRenderSchema` subclass for per-dimension
    rendering overrides; defaults to the base schema.
    """
    schema = schema or BaseRenderSchema()
    root = schema.render_envelope(envelope)
    return MarkdownRenderer(
        asset_loader=asset_loader, inline_assets=inline_assets,
    ).render(root)


def render_comparison_markdown(
    dimension_name: str,
    changes: Dict[str, Dict[str, Any]],
    decisions: Optional[Dict[str, Any]] = None,
    *,
    schema: Optional[BaseRenderSchema] = None,
) -> str:
    """Render a per-dimension diff (plus decisions placeholder) as Markdown."""
    schema = schema or BaseRenderSchema()
    root = schema.render_comparison(dimension_name, changes, decisions)
    return MarkdownRenderer().render(root)


__all__ = ["render_envelope_markdown", "render_comparison_markdown"]
