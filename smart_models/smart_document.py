"""SmartDocument — hierarchical knowledge document with structural Mermaid rendering.

A SmartDocument is a Doc-shaped knowledge document that auto-renders to markdown
beginning with an embedded Mermaid `flowchart TD` and followed by the standard
content rendering of children.

File convention:
    <name>.smart.k.json   — source of truth
    <name>.smart.k.md     — auto-generated rendering (Mermaid + content)

Each SmartDocument node may declare:
    - shape: a Mermaid node shape (rect, rounded, stadium, cylinder, ...)
    - links: cross-cutting edges from this node to others (with label & style)

Children form the implicit parent → child edges of the diagram. Links add
non-tree edges so the model can express system designs, not just hierarchies.
"""

from __future__ import annotations

import re
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# Setup import path for RenderableModel (parallel pattern to state_machine/models/*.py)
_knowledge_src = (
    Path(__file__).parent.parent
    / "plugin" / "knowledge_tool" / "knowledge_tool" / "src"
)
if str(_knowledge_src) not in sys.path:
    sys.path.insert(0, str(_knowledge_src))

from models.base_model import RenderableModel  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────

_MERMAID_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_]")
_HEADING_ANCHOR_STRIP = re.compile(r"[^\w\s-]")
_HEADING_ANCHOR_DASH = re.compile(r"[\s_]+")


def _mermaid_id(s: str) -> str:
    """Sanitize an id for use as a Mermaid node identifier."""
    safe = _MERMAID_ID_UNSAFE.sub("_", s)
    return safe or "node"


def _mermaid_label(s: str) -> str:
    """Escape a label string for inclusion inside Mermaid node text."""
    return s.replace('"', "&quot;")


def _heading_anchor(label: str) -> str:
    """Convert a heading label to a GitHub-style markdown anchor."""
    s = _HEADING_ANCHOR_STRIP.sub("", label.lower())
    return _HEADING_ANCHOR_DASH.sub("-", s).strip("-")


# ── shapes & edges ───────────────────────────────────────────────────────

class NodeShape(str, Enum):
    """Mermaid flowchart node shapes."""

    RECT = "rect"                    # id["text"]      default rectangle
    ROUNDED = "rounded"              # id("text")      rounded rectangle
    STADIUM = "stadium"              # id(["text"])    stadium-shaped
    SUBROUTINE = "subroutine"        # id[["text"]]    double-bordered rectangle
    CYLINDER = "cylinder"            # id[("text")]    cylinder (database)
    CIRCLE = "circle"                # id(("text"))    circle
    ASYMMETRIC = "asymmetric"        # id>"text"]      asymmetric / flag
    RHOMBUS = "rhombus"              # id{"text"}      rhombus / decision diamond
    HEXAGON = "hexagon"              # id{{"text"}}    hexagon
    PARALLELOGRAM = "parallelogram"  # id[/"text"/]    parallelogram (right)
    TRAPEZOID = "trapezoid"          # id[/"text"\]    trapezoid


_SHAPE_WRAPPERS: Dict[NodeShape, tuple] = {
    NodeShape.RECT:          ('["',  '"]'),
    NodeShape.ROUNDED:       ('("',  '")'),
    NodeShape.STADIUM:       ('(["', '"])'),
    NodeShape.SUBROUTINE:    ('[["', '"]]'),
    NodeShape.CYLINDER:      ('[("', '")]'),
    NodeShape.CIRCLE:        ('(("', '"))'),
    NodeShape.ASYMMETRIC:    ('>"',  '"]'),
    NodeShape.RHOMBUS:       ('{"',  '"}'),
    NodeShape.HEXAGON:       ('{{"', '"}}'),
    NodeShape.PARALLELOGRAM: ('[/"', '"/]'),
    NodeShape.TRAPEZOID:     ('[/"', '"\\]'),
}


class EdgeStyle(str, Enum):
    """Mermaid flowchart edge visual styles."""

    ARROW = "arrow"          # -->         default directed arrow
    LINE = "line"            # ---         line, no arrowhead
    THICK = "thick"          # ==>         thick directed arrow
    DOTTED = "dotted"        # -.->        dotted directed arrow
    INVISIBLE = "invisible"  # ~~~         invisible (used for layout hints)


class Link(BaseModel):
    """A directed cross-cutting edge from one SmartDocument node to another.

    Children form the tree edges of the diagram automatically. Use Link for
    non-tree edges: cross-references, dependencies, system-design connections.
    The `target` must be the `id` of another SmartDocument anywhere in the
    document tree.
    """

    target: str = Field(description="Target SmartDocument id")
    label: Optional[str] = Field(default=None, description="Optional edge label")
    style: EdgeStyle = Field(default=EdgeStyle.ARROW, description="Edge visual style")


def _format_edge(
    source_id: str,
    target_id: str,
    label: Optional[str],
    style: EdgeStyle,
) -> str:
    """Format a single Mermaid edge line."""
    src = _mermaid_id(source_id)
    tgt = _mermaid_id(target_id)
    lbl = _mermaid_label(label) if label else None

    if style == EdgeStyle.INVISIBLE:
        return f"{src} ~~~ {tgt}"
    if style == EdgeStyle.DOTTED:
        if lbl:
            return f'{src} -. "{lbl}" .-> {tgt}'
        return f"{src} -.-> {tgt}"
    if style == EdgeStyle.THICK:
        if lbl:
            return f'{src} ==>|"{lbl}"| {tgt}'
        return f"{src} ==> {tgt}"
    if style == EdgeStyle.LINE:
        if lbl:
            return f'{src} ---|"{lbl}"| {tgt}'
        return f"{src} --- {tgt}"
    # default ARROW
    if lbl:
        return f'{src} -->|"{lbl}"| {tgt}'
    return f"{src} --> {tgt}"


# ── the model ────────────────────────────────────────────────────────────

class SmartDocument(RenderableModel):
    """A hierarchical knowledge document with auto-generated Mermaid structure rendering.

    SmartDocuments use the `.smart.k.json` / `.smart.k.md` file naming convention.
    The rendered markdown begins with a Mermaid `flowchart TD` showing the
    document's top-level structure (children + explicit links), followed by
    the content body.

    Each node may specify a Mermaid `shape` and a list of cross-cutting `links`
    to other nodes, enabling expressive system-design diagrams as well as
    plain hierarchies.
    """

    type: Literal["SmartDocument"] = "SmartDocument"
    model_version: int = 1

    id: str = Field(
        description="Stable identifier; only [A-Za-z0-9_] characters render in Mermaid",
    )
    label: str = Field(
        description="Display label; appears as the Mermaid node text and section heading",
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional prose description rendered after the diagram, before children",
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata fields (preserved verbatim)",
    )
    opts: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Rendering options. Recognized keys: "
            "diagram_depth (int, default 1) — depth of the Mermaid tree from this node; "
            "toc (bool, default true) — include a TOC of immediate children."
        ),
    )

    shape: NodeShape = Field(
        default=NodeShape.RECT,
        description="Mermaid flowchart node shape for this node",
    )
    links: List[Link] = Field(
        default_factory=list,
        description="Cross-cutting edges from this node to other nodes (by id)",
    )

    children: Dict[str, "SmartDocument"] = Field(
        default_factory=dict,
        description="Nested SmartDocuments keyed by id; produces tree edges in the diagram",
    )

    @classmethod
    def create_default(cls) -> "SmartDocument":
        """Create a default SmartDocument instance for testing or creation."""
        return cls(
            id=f"{cls.__name__.lower()}_1",
            label=f"{cls.__name__} Document",
        )

    def is_can_be_root(self) -> bool:
        return True

    def render(self, include_toc: bool = True) -> str:
        """Render as markdown: title + Mermaid diagram + (optional TOC) + description + children."""
        lines: List[str] = [f"# {self.label}", ""]
        lines.extend(self._render_mermaid_block())

        toc_enabled = bool(self.opts.get("toc", include_toc))
        if toc_enabled and self.children:
            lines.extend(self._render_toc_block())

        if self.description:
            lines.append(self.description)
            lines.append("")

        for child in self.children.values():
            lines.extend(child._render_as_section(level=2))

        return "\n".join(lines).rstrip() + "\n"

    def render_toc(self) -> List[str]:
        """Top-level TOC entries (immediate children only)."""
        return [
            f"- [{child.label}](#{_heading_anchor(child.label)})"
            for child in self.children.values()
        ]

    # ── internals ────────────────────────────────────────────────────────

    def _diagram_depth(self) -> int:
        depth = self.opts.get("diagram_depth", 1)
        try:
            return max(0, int(depth))
        except (TypeError, ValueError):
            return 1

    def _render_mermaid_block(self) -> List[str]:
        nodes: List[str] = []
        edges: List[str] = []
        clicks: List[str] = []
        seen: set = set()
        self._collect_mermaid(
            nodes=nodes,
            edges=edges,
            clicks=clicks,
            seen=seen,
            current_depth=0,
            max_depth=self._diagram_depth(),
            is_root=True,
        )

        block = ["```mermaid", "flowchart TD"]
        block.extend(f"    {n}" for n in nodes)
        block.extend(f"    {e}" for e in edges)
        if clicks:
            block.append("")
            block.extend(f"    {c}" for c in clicks)
        block.append("```")
        block.append("")
        return block

    def _collect_mermaid(
        self,
        nodes: List[str],
        edges: List[str],
        clicks: List[str],
        seen: set,
        current_depth: int,
        max_depth: int,
        is_root: bool,
    ) -> None:
        my_id = _mermaid_id(self.id)
        if my_id not in seen:
            seen.add(my_id)
            wrapper_open, wrapper_close = _SHAPE_WRAPPERS[self.shape]
            nodes.append(
                f"{my_id}{wrapper_open}{_mermaid_label(self.label)}{wrapper_close}"
            )
            # non-root nodes are wired to their section anchor in the rendered markdown.
            # `_parent` target is required because most renderers iframe the Mermaid
            # block; without it, the relative `#anchor` URL resolves inside the iframe
            # and the click goes nowhere visible. The link target is unquoted per
            # Mermaid grammar (LINK_TARGET token, not STR).
            if not is_root:
                anchor = _heading_anchor(self.label)
                if anchor:
                    clicks.append(
                        f'click {my_id} href "#{anchor}" _self'
                    )

        # explicit cross-cutting links — always rendered, regardless of depth
        for link in self.links:
            edges.append(_format_edge(self.id, link.target, link.label, link.style))

        # tree edges — recurse only while within depth budget
        if current_depth < max_depth:
            for child in self.children.values():
                child_id = _mermaid_id(child.id)
                edges.append(f"{my_id} --> {child_id}")
                child._collect_mermaid(
                    nodes=nodes,
                    edges=edges,
                    clicks=clicks,
                    seen=seen,
                    current_depth=current_depth + 1,
                    max_depth=max_depth,
                    is_root=False,
                )

    def _render_toc_block(self) -> List[str]:
        if not self.children:
            return []
        lines = ["## Contents", ""]
        for child in self.children.values():
            lines.append(f"- [{child.label}](#{_heading_anchor(child.label)})")
        lines.append("")
        return lines

    def _render_as_section(self, level: int) -> List[str]:
        """Render this SmartDocument as a nested section under a parent."""
        prefix = "#" * min(level, 6)
        lines = [f"{prefix} {self.label}", ""]
        if self.description:
            lines.append(self.description)
            lines.append("")
        for child in self.children.values():
            lines.extend(child._render_as_section(level=level + 1))
        return lines


SmartDocument.model_rebuild()
