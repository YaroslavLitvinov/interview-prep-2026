"""Markdown renderer — IR → markdown string.

Walks a `ReportNode` tree and emits the markdown the framework has
historically produced. Per-type dispatch (`render_<type>`) — adding a
new node type means one new method here, no edits to existing methods.
"""

from __future__ import annotations

import base64
from typing import Any, Callable, Dict, List, Optional

from dimensions.render_ir import Attachment, ReportNode


def _collect_leaves(
    root: Optional[Dict[str, Any]],
) -> List[tuple]:
    """Walk a dom_tree, return list of (leaf_node, [ancestors_innermost…outermost])."""
    if root is None:
        return []
    out: List[tuple] = []

    def walk(n: Dict[str, Any], anc: List[Dict[str, Any]]) -> None:
        children = n.get("children") or []
        if not children:
            out.append((n, list(reversed(anc))))
        else:
            for c in children:
                walk(c, anc + [n])

    walk(root, [])
    return out


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
    HTML_PREVIEW_LINES = 60
    TABLE_ROW_LIMIT    = 50
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

    def render_envelope(self, node: ReportNode) -> List[str]:
        d = node.data
        out = [
            f"## Dimension: `{d['dimension']}` · envelope `{d['envelope_name']}` "
            f"(category: `{d['category']}`)",
            "",
            f"- **Captured:** `{d['captured_at']}`",
            f"- **Subject:** {self._md_subject(d['subject'])}",
            "",
        ]
        for child in node.children:
            out.extend(self._render(child))
            out.append("")
        return out

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
        return [f"- **{d['label']}** (`{d['id']}`): `{d['value']}`{unit}"]

    def render_status_line(self, node: ReportNode) -> List[str]:
        d = node.data
        marker = "✅" if d["value"] else "❌"
        return [f"- {marker} **{d['label']}** (`{d['id']}`)"]

    def render_rule_result(self, node: ReportNode) -> List[str]:
        d = node.data
        checked = d.get("checked_count")
        scope = f" — {checked} checked" if checked is not None else ""
        if d["passed"]:
            return [f"- ✅ **{d['label']}** (`{d['id']}`){scope}"]
        out = [
            f"- ❌ **{d['label']}** (`{d['id']}`){scope} — "
            f"{d.get('violations_count', 0)} violations"
        ]
        for v in d.get("violations_sample", [])[: self.VIOLATION_SAMPLE]:
            out.append(f"    - `{v}`")
        return out

    def render_set_summary(self, node: ReportNode) -> List[str]:
        d = node.data
        items = d.get("items", [])
        if len(items) <= self.INLINE_SET_LIMIT:
            return [f"- **{d['label']}** (`{d['id']}`): {len(items)} items — `{items}`"]
        preview = items[: self.SET_PREVIEW]
        return [
            f"- **{d['label']}** (`{d['id']}`): {len(items)} items, "
            f"e.g. `{preview}` _… +{len(items) - self.SET_PREVIEW} more_"
        ]

    def render_distribution_table(self, node: ReportNode) -> List[str]:
        d = node.data
        rows = d.get("rows", [])
        out = [
            f"- **{d['label']}** (`{d['id']}`): {d['unique']} keys, total={d['total']}",
            "",
            "    | Key | Count |",
            "    |---|---|",
        ]
        for k, v in rows[: self.DISTRIB_TOP]:
            out.append(f"    | `{k}` | {v} |")
        if len(rows) > self.DISTRIB_TOP:
            out.append(f"    | _… +{len(rows) - self.DISTRIB_TOP} more_ | |")
        return out

    def render_histogram_table(self, node: ReportNode) -> List[str]:
        d = node.data
        rows = d.get("rows", [])
        out = [
            f"- **{d['label']}** (`{d['id']}`): {d['unique']} unique, "
            f"total={d['total']}",
            "",
            "    | Item | Count |",
            "    |---|---|",
        ]
        for k, count in rows[: self.HISTOGRAM_TOP]:
            out.append(f"    | `{k}` | {count} |")
        return out

    # ── payload node renderers ───────────────────────────────────────

    def render_html_excerpt(self, node: ReportNode) -> List[str]:
        d = node.data
        html_lines = (d.get("html") or "").splitlines()
        out = [
            f"- **{d['label']}** (`{d['id']}`) — payload `html`",
            f"    - URL: `{d.get('url')}`",
            f"    - Status: `{d.get('status')}`",
            f"    - Length: {d.get('length', 0)} chars",
            "",
            "    ```html",
            *(f"    {ln}" for ln in html_lines[: self.HTML_PREVIEW_LINES]),
            *(["    …"] if len(html_lines) > self.HTML_PREVIEW_LINES else []),
            "    ```",
        ]
        return out

    def render_record_table(self, node: ReportNode) -> List[str]:
        d = node.data
        cols = d.get("columns", [])
        rows = d.get("rows", [])
        out = [
            f"- **{d['label']}** (`{d['id']}`) — payload `{d['schema']}` "
            f"— {len(rows)} rows × {len(cols)} columns",
            "",
            "    | " + " | ".join(cols) + " |",
            "    |" + "|".join("---" for _ in cols) + "|",
        ]
        for row in rows[: self.TABLE_ROW_LIMIT]:
            if isinstance(row, dict):
                cells = [str(row.get(c, ""))[:80].replace("|", "\\|") for c in cols]
            elif isinstance(row, list):
                cells = [str(c)[:80].replace("|", "\\|") for c in row]
            else:
                cells = [str(row)]
            out.append("    | " + " | ".join(cells) + " |")
        if len(rows) > self.TABLE_ROW_LIMIT:
            out.append(f"    | _… +{len(rows) - self.TABLE_ROW_LIMIT} more_ |")
        return out

    def render_image(self, node: ReportNode) -> List[str]:
        d = node.data
        out = [
            f"- **{d['label']}** (`{d['id']}`) — payload `screenshot`",
            f"    - Format: `{d.get('format')}`",
            f"    - Size: {d.get('width')}×{d.get('height')} px, "
            f"{d.get('size_bytes')} bytes",
            f"    - sha256: `{d.get('sha256') or ''}`",
            "",
        ]
        # Inline as data URL when an asset_loader is available; else
        # emit a relative `ref` link (works when MD lives next to assets).
        img_src = self._image_src(node)
        if img_src:
            out.append(f"![{d['label']}]({img_src})")
        return out

    def render_accessibility(self, node: ReportNode) -> List[str]:
        d = node.data
        return [
            f"- **{d['label']}** (`{d['id']}`) — payload `accessibility_tree`",
            "    - _(accessibility tree — JSON payload)_",
        ]

    # ── dom_tree (leaves at top, ancestors revealed below) ───────────────

    DOM_LEAVES_CAP      = 100   # markdown is verbose; cap tighter than HTML
    DOM_TREE_NODE_LIMIT = 1000
    DOM_SKIPPED_PREVIEW = 50

    def render_dom_tree(self, node: ReportNode) -> List[str]:
        d = node.data
        flt = d.get("filter")
        flt_desc = (
            f" — filter `{flt}`, with_hierarchy=`{d.get('with_hierarchy')}`"
            if flt else " — no filter (full tree)"
        )
        leaves = _collect_leaves(d.get("root"))
        out = [
            f"- **{d['label']}** (`{d['id']}`) — payload `dom_tree`{flt_desc}",
            f"    - Nodes: {d.get('node_count', 0):,}, "
            f"kept: {d.get('kept_count', 0):,}, "
            f"skipped: {d.get('skipped_count', 0):,}, "
            f"leaves: {len(leaves):,}",
            "",
        ]
        count = [0]
        for leaf, ancestors in leaves[: self.DOM_LEAVES_CAP]:
            if count[0] >= self.DOM_TREE_NODE_LIMIT:
                break
            self._md_emit_leaf(leaf, ancestors, indent=4, out=out, count=count)
        if len(leaves) > self.DOM_LEAVES_CAP:
            out.append(
                f"    _… +{len(leaves) - self.DOM_LEAVES_CAP:,} "
                f"more leaves omitted_"
            )

        skipped = d.get("skipped") or []
        if skipped:
            out.append("")
            out.append(f"    <details><summary>Skipped ({len(skipped):,})</summary>")
            out.append("")
            for s in skipped[: self.DOM_SKIPPED_PREVIEW]:
                tag_id = f"{s.get('tag','?')}"
                if s.get("id"):
                    tag_id += f"#{s['id']}"
                cls = ".".join(s.get("classes") or [])
                if cls:
                    tag_id += f".{cls}"
                out.append(f"    - `{tag_id}` _({s.get('reason','')})_")
            if len(skipped) > self.DOM_SKIPPED_PREVIEW:
                out.append(
                    f"    - _… +{len(skipped) - self.DOM_SKIPPED_PREVIEW:,} more_"
                )
            out.append("    </details>")
        return out

    def _md_emit_leaf(
        self,
        leaf: Dict[str, Any],
        ancestors: List[Dict[str, Any]],
        *,
        indent: int,
        out: List[str],
        count: List[int],
    ) -> None:
        prefix = " " * indent
        out.append(f"{prefix}- {self._md_node_summary(leaf)}")
        count[0] += 1
        for k, v in self._md_node_props(leaf):
            out.append(f"{prefix}    - {k}: `{v}`")
        if ancestors:
            # Compact breadcrumb only — props rendered on the leaf, not on
            # every ancestor (otherwise every shared ancestor's CSS gets
            # duplicated across every descendant leaf).
            out.append(f"{prefix}    - **Ancestors (innermost → root):**")
            for anc in ancestors:
                out.append(f"{prefix}        - {self._md_node_summary(anc)}")

    def _md_node_summary(self, n: Dict[str, Any]) -> str:
        tag = n.get("tag", "?")
        marker = "·" if n.get("connector") else "•"
        attrs: List[str] = []
        if n.get("id"):
            attrs.append(f"#{n['id']}")
        if n.get("classes"):
            attrs.append("." + ".".join(n["classes"][:3]))
        if n.get("role"):
            attrs.append(f"[role={n['role']}]")
        text = (n.get("text") or "").strip()
        text_str = f' "{text[:40]}"' if text else ""
        bbox = ""
        if (n.get("width") or 0) and (n.get("height") or 0):
            bbox = f" @{n['x']},{n['y']} {n['width']}×{n['height']}"
        return f"{marker} `{tag}{''.join(attrs)}`{bbox}{text_str}"

    def _md_node_props(self, n: Dict[str, Any]) -> List[tuple]:
        rows: List[tuple] = []
        text = (n.get("text") or "").strip()
        if text and len(text) > 40:
            rows.append(("text", text[:200]))
        if n.get("aria_label"):
            rows.append(("aria-label", str(n["aria_label"])))
        if n.get("position"):
            rows.append(("position", str(n["position"])))
        if n.get("z_index"):
            rows.append(("z-index", str(n["z_index"])))
        rows.append(("visible", "yes" if n.get("visible") else "no"))
        style = n.get("computed_style") or {}
        if isinstance(style, dict):
            for k, v in style.items():
                if v in (None, "", "auto", "normal"):
                    continue
                rows.append((f"css/{k}", str(v)))
        attrs = n.get("attributes") or {}
        if isinstance(attrs, dict):
            for k, v in attrs.items():
                rows.append((f"attr/{k}", str(v)[:200]))
        return rows

    def render_unknown_payload(self, node: ReportNode) -> List[str]:
        d = node.data
        return [
            f"- **{d['label']}** (`{d['id']}`) — payload `{d['payload_schema']}`",
            f"    - _data type: {d.get('data_type', '?')}_",
        ]

    def render_unknown_obs(self, node: ReportNode) -> List[str]:
        d = node.data
        return [f"- ? **{d['label']}** (`{d['id']}`): unknown kind={d['kind']}"]

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

        if schema in {"elements", "layered", "interactive"}:
            added = raw.get("added") or []
            removed = raw.get("removed") or []
            modified = raw.get("modified") or {}
            out = [head]
            if added:
                out.append(f"- **Added:** {len(added)} row(s)")
                for r in added[:10]:
                    out.append(f"    - `{r.get('selector', r) if isinstance(r, dict) else r}`")
            if removed:
                out.append(f"- **Removed:** {len(removed)} row(s)")
                for r in removed[:10]:
                    out.append(f"    - `{r.get('selector', r) if isinstance(r, dict) else r}`")
            if modified:
                out.append(f"- **Modified:** {len(modified)} row(s)")
                for sel in list(modified.keys())[:10]:
                    out.append(f"    - `{sel}`")
            return out

        if schema == "html":
            return [
                head,
                f"- Length: `{raw.get('length_before')}` → `{raw.get('length_after')}` chars",
                f"- Status: `{raw.get('status_before')}` → `{raw.get('status_after')}`",
                f"- First diff offset: `{raw.get('first_diff_offset')}`",
            ]

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
