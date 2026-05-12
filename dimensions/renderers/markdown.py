"""Markdown renderer — IR → markdown string.

Walks a `ReportNode` tree and emits the markdown the framework has
historically produced. Per-type dispatch (`render_<type>`) — adding a
new node type means one new method here, no edits to existing methods.
"""

from __future__ import annotations

import base64
from typing import Any, Callable, Dict, List, Optional

from dimensions.render_ir import Attachment, ReportNode


class MarkdownRenderer:
    """ReportNode tree → markdown string.

    Asset handling (image references in `screenshot` payloads):

      * ``inline_assets=True`` (default) — image bytes embed as base64
        data URLs via ``asset_loader``. The markdown is self-contained,
        viewable from anywhere.
      * ``inline_assets=False`` — image refs use the relative ``ref``
        path (``assets/<sha>.<ext>``). Smaller markdown; the file must
        live next to the snapshot's ``assets/`` directory for refs to
        resolve. Use the ``render-md`` CLI command (or copy assets
        alongside yourself) when emitting many reports to a directory.

    ``asset_loader`` is a callable mapping ``sha256 -> bytes``. Required
    only when ``inline_assets=True`` and the envelope carries assets.
    """

    # truncation limits (also exposed as overridable class attrs)
    INLINE_SET_LIMIT   = 10
    SET_PREVIEW        = 8
    DISTRIB_TOP        = 10
    HISTOGRAM_TOP      = 10
    VIOLATION_SAMPLE   = 5

    def __init__(
        self,
        *,
        asset_loader: Optional[Callable[[str], bytes]] = None,
        inline_assets: bool = True,
    ) -> None:
        self.asset_loader = asset_loader
        self.inline_assets = inline_assets

    # ── public entry ─────────────────────────────────────────────────

    def render(self, node: ReportNode) -> str:
        return "\n".join(self._render(node))

    # ── dispatch ─────────────────────────────────────────────────────

    def _render(self, node: ReportNode) -> List[str]:
        method = getattr(self, f"render_{node.type}", self.render_unknown)
        lines = method(node)
        if node.required and lines:
            lines[0] = lines[0] + " · **required**"
        return lines

    # ── envelope / comparison roots ──────────────────────────────────

    # Stability tier → glyph. Kept in one place so envelope, screen_map,
    # and (future) scenario renderers stay visually consistent.
    TIER_GLYPHS = {
        "STRONG": "🟢",
        "MEDIUM": "🟡",
        "WEAK":   "🔴",
    }

    def render_envelope(self, node: ReportNode) -> List[str]:
        d = node.data
        attachments_total = sum(
            len(c.attachments) for c in self._iter_descendants(node)
        )
        chips = [
            f"**Observations:** {len(node.children)}",
            f"**Attachments:** {attachments_total}",
            f"**Captured:** `{d['captured_at']}`",
        ]
        out = [
            f"# `{d['dimension']}` · `{d['envelope_name']}`",
            "",
            f"**Subject:** {self._md_subject(d['subject'])}",
            " · ".join(chips),
            "",
        ]

        # Observations section
        if node.children:
            out.append("## Observations")
            out.append("")
            for child in node.children:
                out.extend(self._render_card(child))
                out.append("")

        # Attachments section (flat list across all children)
        attachments = list(self._iter_attachments(node))
        if attachments:
            out.append("## Attachments")
            out.append("")
            for att in attachments:
                ref = att.asset_ref or {}
                out.append(self._md_attachment_line(att, ref))
            out.append("")

        # Provenance section — caller may pre-populate node.data["provenance"]
        prov = d.get("provenance")
        if prov:
            out.append("## Provenance")
            out.append("")
            out.append(self._md_provenance_line(prov))
            out.append("")

        return out

    # ── card wrapper ─────────────────────────────────────────────────

    # Per-IR-type chip data: (kind label, optional payload schema label).
    _CARD_CHIPS = {
        "field":              ("scalar", None),
        "status_line":        ("boolean", None),
        "rule_result":        ("rule_check", None),
        "set_summary":        ("set", None),
        "distribution_table": ("distribution", None),
        "histogram_table":    ("histogram", None),
        "image":              ("payload", "screenshot"),
        "dom_tree":           ("payload", "dom_tree"),
        "screen_map":         ("payload", "screen_map"),
        "unknown_payload":    ("payload", "?"),
        "unknown_obs":        ("?", None),
    }

    def _render_card(self, node: ReportNode) -> List[str]:
        """Render one observation as an H3 card + body."""
        if node.type == "hidden":
            return []
        d = node.data if isinstance(node.data, dict) else {}
        obs_id = d.get("id") or "?"
        label  = d.get("label") or obs_id
        kind, schema = self._CARD_CHIPS.get(node.type, (node.type, None))
        chip = kind if schema is None else f"{kind} · {schema}"
        size = self._card_size(node)
        if size:
            chip = f"{chip} · {size}"
        header = f"### `{obs_id}` &nbsp; <sub>{chip}</sub>"
        if label and label != obs_id:
            header += f"  \n_{label}_"
        body = self._render(node)
        out = [header, ""]
        out.extend(body)
        if node.required:
            out.append("")
            out.append("> **required**")
        return out

    def _card_size(self, node: ReportNode) -> Optional[str]:
        d = node.data if isinstance(node.data, dict) else {}
        t = node.type
        if t == "dom_tree":
            n = d.get("kept_count") or d.get("node_count") or 0
            return f"{n:,} node{'s' if n != 1 else ''}"
        if t == "screen_map":
            n = d.get("element_count") or 0
            return f"{n:,} element{'s' if n != 1 else ''}"
        if t == "set_summary":
            n = len(d.get("items") or [])
            return f"{n:,} item{'s' if n != 1 else ''}"
        if t == "distribution_table":
            return f"{d.get('unique', 0):,} keys · total {d.get('total', 0):,}"
        if t == "histogram_table":
            return f"{d.get('unique', 0):,} unique · total {d.get('total', 0):,}"
        if t == "rule_result":
            checked = d.get("checked_count")
            return f"{checked:,} checked" if checked is not None else None
        if t == "image":
            w, h = d.get("width"), d.get("height")
            return f"{w}×{h} px" if w and h else None
        return None

    def _iter_descendants(self, node: ReportNode):
        yield node
        for c in node.children:
            yield from self._iter_descendants(c)

    def _iter_attachments(self, node: ReportNode):
        for n in self._iter_descendants(node):
            for att in n.attachments:
                yield att

    def _md_attachment_line(self, att: Attachment, ref: Dict[str, Any]) -> str:
        sha = ref.get("sha256") or ""
        sha_short = sha[:12] + "…" if sha else "?"
        size = ref.get("size_bytes")
        size_str = f" · {size:,} B" if isinstance(size, int) else ""
        return f"- `{sha_short}` · `{att.mime_type}` · **{att.name}**{size_str}"

    def _md_provenance_line(self, prov: Dict[str, Any]) -> str:
        plugin = prov.get("plugin", "?")
        name   = prov.get("name", "?")
        path   = prov.get("path")
        link   = f"[`{plugin}/{name}`]({path})" if path else f"`{plugin}/{name}`"
        return f"Driven by scenario → {link}"

    def render_comparison(self, node: ReportNode) -> List[str]:
        d = node.data
        out = [f"## Dimension: `{d['dimension_name']}`", ""]
        if d.get("change_count", 0) == 0:
            out += ["✅ No changes detected.", ""]
        else:
            out += [f"**{d['change_count']} change(s) detected.**", ""]
            for child in node.children:
                out.extend(self._render(child))
                out.append("")
        decisions = d.get("decisions")
        if decisions is not None:
            out.append("### Decisions")
            out.append("")
            if not decisions:
                out.append(
                    "_(none recorded — attach approve/decline verdicts here; "
                    "snapshots themselves stay immutable.)_"
                )
                out.append("")
            else:
                out.append("| Change (observation id) | Verdict |")
                out.append("|---|---|")
                for oid in sorted(decisions.keys()):
                    out.append(f"| `{oid}` | `{decisions[oid]}` |")
                out.append("")
        return out

    # ── observation node renderers ───────────────────────────────────

    def render_field(self, node: ReportNode) -> List[str]:
        d = node.data
        unit = f" {d['unit']}" if d.get("unit") else ""
        return [f"`{d['value']}`{unit}"]

    def render_status_line(self, node: ReportNode) -> List[str]:
        d = node.data
        return ["✓ true" if d["value"] else "✗ false"]

    def render_rule_result(self, node: ReportNode) -> List[str]:
        d = node.data
        if d["passed"]:
            return ["✓ passed"]
        out = [f"✗ **{d.get('violations_count', 0)} violations**", ""]
        for v in d.get("violations_sample", [])[: self.VIOLATION_SAMPLE]:
            out.append(f"- `{v}`")
        more = d.get("violations_count", 0) - self.VIOLATION_SAMPLE
        if more > 0:
            out.append(f"- _… +{more:,} more_")
        return out

    def render_set_summary(self, node: ReportNode) -> List[str]:
        d = node.data
        items = d.get("items", [])
        if len(items) <= self.INLINE_SET_LIMIT:
            return [f"- `{i}`" for i in items] or ["_(empty)_"]
        out = [f"- `{i}`" for i in items[: self.SET_PREVIEW]]
        out.append(f"- _… +{len(items) - self.SET_PREVIEW:,} more_")
        return out

    def render_distribution_table(self, node: ReportNode) -> List[str]:
        d = node.data
        rows = d.get("rows", [])
        out = ["| Key | Count |", "|---|---|"]
        for k, v in rows[: self.DISTRIB_TOP]:
            out.append(f"| `{k}` | {v} |")
        if len(rows) > self.DISTRIB_TOP:
            out.append(f"| _… +{len(rows) - self.DISTRIB_TOP} more_ | |")
        return out

    def render_histogram_table(self, node: ReportNode) -> List[str]:
        d = node.data
        rows = d.get("rows", [])
        out = ["| Item | Count |", "|---|---|"]
        for k, count in rows[: self.HISTOGRAM_TOP]:
            out.append(f"| `{k}` | {count} |")
        return out

    # ── payload node renderers ───────────────────────────────────────

    def render_image(self, node: ReportNode) -> List[str]:
        d = node.data
        meta = []
        if d.get("format"):
            meta.append(f"`{d['format']}`")
        if d.get("size_bytes"):
            meta.append(f"{d['size_bytes']:,} B")
        if d.get("sha256"):
            meta.append(f"sha `{d['sha256'][:12]}…`")
        out = [" · ".join(meta)] if meta else []
        out.append("")
        img_src = self._image_src(node)
        if img_src:
            label = d.get("label") or d.get("id") or "screenshot"
            out.append(f"![{label}]({img_src})")
        return out


    @staticmethod
    def _escape_md(s: str) -> str:
        # Conservative: escape pipes (table) and backticks. Newlines → space.
        return s.replace("|", "\\|").replace("`", "\\`").replace("\n", " ")

    # ── dom_tree (leaves at top, ancestors revealed below) ───────────────

    DOM_LEAVES_CAP      = 100   # markdown is verbose; cap tighter than HTML
    DOM_TREE_NODE_LIMIT = 1000
    DOM_SKIPPED_PREVIEW = 50

    def render_dom_tree(self, node: ReportNode) -> List[str]:
        d = node.data
        flt = d.get("filter")
        chips = [
            f"{d.get('kept_count', 0):,} kept",
            f"{d.get('skipped_count', 0):,} skipped",
            f"{d.get('node_count', 0):,} total",
        ]
        if flt:
            chips.append(f"filter `{flt}`")
        else:
            chips.append("no filter")
        out = [" · ".join(chips), "", "```"]

        root = d.get("root")
        emitted = [0]
        if root:
            self._tree_lines(root, prefix="", is_last=True, is_root=True,
                             out=out, emitted=emitted,
                             cap=self.DOM_TREE_NODE_LIMIT)
            if emitted[0] >= self.DOM_TREE_NODE_LIMIT:
                out.append(f"… (truncated at {self.DOM_TREE_NODE_LIMIT:,} nodes)")
        else:
            out.append("(empty)")
        out.append("```")

        skipped = d.get("skipped") or []
        if skipped:
            out.append("")
            out.append(
                f"<details><summary>Skipped ({len(skipped):,})</summary>"
            )
            out.append("")
            for s in skipped[: self.DOM_SKIPPED_PREVIEW]:
                tag_id = f"{s.get('tag','?')}"
                if s.get("id"):
                    tag_id += f"#{s['id']}"
                cls = ".".join(s.get("classes") or [])
                if cls:
                    tag_id += f".{cls}"
                out.append(f"- `{tag_id}` _({s.get('reason','')})_")
            if len(skipped) > self.DOM_SKIPPED_PREVIEW:
                out.append(
                    f"- _… +{len(skipped) - self.DOM_SKIPPED_PREVIEW:,} more_"
                )
            out.append("")
            out.append("</details>")
        return out

    def _tree_lines(
        self,
        node: Dict[str, Any],
        *,
        prefix: str,
        is_last: bool,
        is_root: bool,
        out: List[str],
        emitted: List[int],
        cap: int,
    ) -> None:
        if emitted[0] >= cap:
            return
        if is_root:
            label = self._tree_node_label(node)
            out.append(label)
            child_prefix = ""
        else:
            connector = "└── " if is_last else "├── "
            out.append(prefix + connector + self._tree_node_label(node))
            child_prefix = prefix + ("    " if is_last else "│   ")
        emitted[0] += 1
        children = node.get("children") or []
        for i, child in enumerate(children):
            self._tree_lines(
                child,
                prefix=child_prefix,
                is_last=(i == len(children) - 1),
                is_root=False,
                out=out,
                emitted=emitted,
                cap=cap,
            )

    def _tree_node_label(self, n: Dict[str, Any]) -> str:
        tag = n.get("tag", "?")
        attrs: List[str] = []
        if n.get("id"):
            attrs.append(f"#{n['id']}")
        if n.get("classes"):
            attrs.append("." + ".".join(n["classes"][:2]))
        node_attrs = n.get("attributes") or {}
        if isinstance(node_attrs, dict):
            if node_attrs.get("testid"):
                attrs.append(f"[testid={node_attrs['testid']}]")
            if node_attrs.get("data-testid"):
                attrs.append(f"[testid={node_attrs['data-testid']}]")
        if n.get("role"):
            attrs.append(f"[role={n['role']}]")
        text = (n.get("text") or "").strip()
        text_str = f'  "{text[:40]}"' if text else ""
        return f"{tag}{''.join(attrs)}{text_str}"

    def render_unknown_payload(self, node: ReportNode) -> List[str]:
        d = node.data
        return [f"_unknown payload schema `{d['payload_schema']}` "
                f"(data type: {d.get('data_type', '?')})_"]

    def render_unknown_obs(self, node: ReportNode) -> List[str]:
        d = node.data
        return [f"_unknown observation kind `{d['kind']}`_"]

    # ── change node renderers ────────────────────────────────────────

    def render_change_added(self, node: ReportNode) -> List[str]:
        return [f"### ➕ `{node.data['id']}` — NEW observation"]

    def render_change_removed(self, node: ReportNode) -> List[str]:
        return [f"### ➖ `{node.data['id']}` — DROPPED observation"]

    def render_change_scalar(self, node: ReportNode) -> List[str]:
        d = node.data
        delta = d.get("delta")
        delta_str = f" (**{delta:+}**)" if isinstance(delta, (int, float)) else ""
        return [
            f"### Δ `{d['id']}` — scalar",
            f"- `{d['before']}` → `{d['after']}`{delta_str}",
        ]

    def render_change_boolean(self, node: ReportNode) -> List[str]:
        d = node.data
        return [
            f"### Δ `{d['id']}` — boolean",
            f"- `{d['before']}` → `{d['after']}`",
        ]

    def render_change_rule(self, node: ReportNode) -> List[str]:
        d = node.data
        out = [f"### ❌ `{d['id']}` — rule_check changed"]
        if d.get("transition"):
            out.append(f"- Status: `{d['transition']}`")
        if d.get("new_violations"):
            out.append(f"- New violations: **+{d['new_violations']}**")
            for v in d.get("new_sample", []):
                out.append(f"    - `{v}`")
        if d.get("resolved_violations"):
            out.append(f"- Resolved: **-{d['resolved_violations']}**")
        if d.get("scope_delta") is not None:
            out.append(
                f"- Scope: `{d.get('scope_before')}` → "
                f"`{d.get('scope_after')}` (**{d['scope_delta']:+}**)"
            )
        return out

    def render_change_set(self, node: ReportNode) -> List[str]:
        d = node.data
        out = [f"### Δ `{d['id']}` — set changed"]
        if d.get("added"):
            out.append(f"- Added: `{d['added']}`")
        if d.get("removed"):
            out.append(f"- Removed: `{d['removed']}`")
        return out

    def render_change_distribution(self, node: ReportNode) -> List[str]:
        d = node.data
        out = [f"### Δ `{d['id']}` — distribution changed"]
        if d.get("added_keys"):
            out.append(f"- New keys: `{d['added_keys']}`")
        if d.get("removed_keys"):
            out.append(f"- Dropped keys: `{d['removed_keys']}`")
        modified = d.get("modified") or {}
        if modified:
            out += ["", "    | Key | Before | After | Δ |", "    |---|---|---|---|"]
            for k, v in modified.items():
                delta = v.get("delta")
                delta_str = f"{delta:+}" if isinstance(delta, (int, float)) else "?"
                out.append(
                    f"    | `{k}` | {v['before']} | {v['after']} | **{delta_str}** |"
                )
        return out

    def render_change_histogram(self, node: ReportNode) -> List[str]:
        d = node.data
        return [
            f"### Δ `{d['id']}` — histogram changed",
            f"- Total: `{d['total_before']}` → `{d['total_after']}`",
            f"- Unique: `{d['unique_before']}` → `{d['unique_after']}`",
        ]

    def render_change_payload(self, node: ReportNode) -> List[str]:
        d = node.data
        schema = d.get("payload_schema") or "?"
        raw = d.get("raw") or {}
        head = f"### Δ `{d['id']}` — payload `{schema}` changed"

        if schema == "screenshot":
            return [
                head,
                f"- sha256: `{(raw.get('sha256_before') or '')[:12]}` → "
                f"`{(raw.get('sha256_after') or '')[:12]}`",
                f"- Size: `{raw.get('size_before')}` → `{raw.get('size_after')}` bytes",
                f"- Dimensions: `{raw.get('width_before')}×{raw.get('height_before')}` → "
                f"`{raw.get('width_after')}×{raw.get('height_after')}`",
            ]

        return [head, "- _payload changed (raw)_"]

    def render_change_unknown(self, node: ReportNode) -> List[str]:
        return [f"### ? `{node.data['id']}` — unknown change kind={node.data['kind']}"]

    # ── fallback ──────────────────────────────────────────────────────

    def render_unknown(self, node: ReportNode) -> List[str]:
        return [f"- ? **{node.type}** (unhandled IR node type)"]

    def render_hidden(self, node: ReportNode) -> List[str]:
        return []

    # ── helpers ───────────────────────────────────────────────────────

    def _md_subject(self, subject: Dict[str, Any]) -> str:
        if not subject:
            return "_(none)_"
        parts = [f"`{k}={v}`" for k, v in subject.items()]
        return " · ".join(parts)

    def _image_src(self, node: ReportNode) -> Optional[str]:
        for att in node.attachments:
            ref = att.asset_ref or {}
            sha = ref.get("sha256")
            if self.inline_assets and self.asset_loader is not None and sha:
                try:
                    content = self.asset_loader(sha)
                    b64 = base64.b64encode(content).decode("ascii")
                    return f"data:{att.mime_type};base64,{b64}"
                except Exception:  # noqa: BLE001
                    pass
            if ref.get("ref"):
                return ref["ref"]
        return None
