"""Render IR — a target-agnostic report tree.

Envelopes and diff results are translated into a tree of `ReportNode`s
by a `RenderSchema`. Each render target (Markdown today; HTML / Allure
/ etc. tomorrow) consumes the IR — no target sees the raw envelope's
``kind`` / ``payload_schema`` discriminator.

The IR is intentionally tiny. Each node carries a string ``type``
discriminator and a ``data`` dict whose shape depends on ``type``;
renderers dispatch per type. New observation kinds or payload schemas
add new node types, not new branches in every renderer.

Recognised node types (extensible — renderers fall back gracefully):

  envelope          — root node for one envelope (header + children)
  comparison        — root node for one (dimension, label) diff (header + children)
  section           — generic grouping (title + children)
  field             — labelled scalar value (key / value / unit?)
  status_line       — labelled boolean (passed/failed)
  rule_result       — rule check (label, status, violations)
  set_summary       — set observation (label, items)
  distribution_table — distribution as a 2-col table
  histogram_table   — histogram top-N as a 2-col table
  record_table      — payload `elements` / `layered` / `interactive`
  html_excerpt      — payload `html`
  image             — payload `screenshot`
  accessibility     — payload `accessibility_tree`
  unknown_payload   — payload with an unrecognised schema
  unknown_obs       — observation with an unrecognised kind

  change_added / change_removed
  change_scalar / change_boolean / change_rule / change_set
  change_distribution / change_histogram / change_payload
  change_unknown

Renderers can do `render_<type>` lookup; if missing, they fall back to
`render_unknown`. Adding a new node type costs one new method per
renderer — but no edits to existing code paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Attachment:
    """A binary or text artifact attached to a report node.

    Exactly one of ``data`` / ``text`` / ``asset_ref`` is populated.
    ``asset_ref`` is a metadata dict (sha256/ref/size_bytes/mime_type)
    that the renderer can use to fetch bytes via an asset loader.
    """

    name: str
    mime_type: str
    data: Optional[bytes] = None
    text: Optional[str] = None
    asset_ref: Optional[Dict[str, Any]] = None


@dataclass
class ReportNode:
    """One node in the render IR tree.

    The schema produces these from envelopes / change records. Renderers
    consume them. ``type`` is the discriminator; ``data`` is shape-typed
    per ``type`` (see module docstring for the catalog).
    """

    type: str
    data: Dict[str, Any] = field(default_factory=dict)
    children: List["ReportNode"] = field(default_factory=list)
    attachments: List[Attachment] = field(default_factory=list)
    required: bool = False
