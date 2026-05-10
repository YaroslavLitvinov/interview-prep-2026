"""RenderSchema — envelope/change → IR tree.

`BaseRenderSchema` knows how to translate every observation kind and
every recognised payload schema into `ReportNode`s. Per-dimension
subclasses override only the methods they want to change — the rest
inherit. Renderers consume the IR; they never see envelopes.

Override hooks (every method below):

    render_envelope(envelope) -> ReportNode
    render_comparison(dimension_name, changes, decisions) -> ReportNode

    render_observation(obs) -> ReportNode             # per-kind dispatch
    render_scalar / render_boolean / render_rule_check /
    render_set / render_distribution / render_histogram / render_payload

    render_payload(obs) -> ReportNode                 # per-payload-schema dispatch
    render_payload_html / render_payload_table /
    render_payload_screenshot / render_payload_accessibility /
    render_payload_unknown

    render_change(obs_id, change) -> ReportNode       # per-kind dispatch
    render_change_scalar / render_change_boolean / render_change_rule /
    render_change_set / render_change_distribution / render_change_histogram /
    render_change_payload / render_change_added / render_change_removed
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from dimensions.observation import (
    BOOLEAN, DISTRIBUTION, HISTOGRAM, PAYLOAD, RULE_CHECK, SCALAR, SET,
)
from dimensions.render_ir import Attachment, ReportNode


class BaseRenderSchema:
    """Default schema — handles every kind and every recognised payload schema."""

    # ── top-level entry points ─────────────────────────────────────────

    def render_envelope(self, envelope: Dict[str, Any]) -> ReportNode:
        return ReportNode(
            type="envelope",
            data={
                "dimension":     envelope.get("dimension", "?"),
                "envelope_name": envelope.get("envelope_name", "main"),
                "category":      envelope.get("category", "?"),
                "captured_at":   envelope.get("captured_at", "?"),
                "subject":       envelope.get("subject") or {},
            },
            children=[
                self.render_observation(o)
                for o in envelope.get("observations", [])
            ],
        )

    def render_comparison(
        self,
        dimension_name: str,
        changes: Dict[str, Dict[str, Any]],
        decisions: Optional[Dict[str, Any]] = None,
    ) -> ReportNode:
        return ReportNode(
            type="comparison",
            data={
                "dimension_name": dimension_name,
                "decisions":      dict(decisions) if decisions is not None else None,
                "change_count":   len(changes),
            },
            children=[
                self.render_change(oid, changes[oid])
                for oid in sorted(changes.keys())
            ],
        )

    # ── per-kind observation dispatch ─────────────────────────────────

    def render_observation(self, obs: Dict[str, Any]) -> ReportNode:
        kind = obs.get("kind")
        method = getattr(self, f"render_{kind}", None)
        node = method(obs) if method else self._render_unknown_obs(obs)
        if obs.get("required"):
            node.required = True
        return node

    def render_scalar(self, obs: Dict[str, Any]) -> ReportNode:
        return ReportNode(type="field", data={
            "id":    obs.get("id", ""),
            "label": obs.get("label", ""),
            "value": obs.get("value"),
            "unit":  obs.get("unit"),
        })

    def render_boolean(self, obs: Dict[str, Any]) -> ReportNode:
        return ReportNode(type="status_line", data={
            "id":    obs.get("id", ""),
            "label": obs.get("label", ""),
            "value": bool(obs.get("value")),
        })

    def render_rule_check(self, obs: Dict[str, Any]) -> ReportNode:
        return ReportNode(type="rule_result", data={
            "id":               obs.get("id", ""),
            "label":            obs.get("label", ""),
            "passed":           bool(obs.get("passed")),
            "checked_count":    obs.get("checked_count"),
            "violations_count": obs.get("violations_count", 0),
            "violations_sample": list(obs.get("violations_sample", []) or []),
        })

    def render_set(self, obs: Dict[str, Any]) -> ReportNode:
        return ReportNode(type="set_summary", data={
            "id":    obs.get("id", ""),
            "label": obs.get("label", ""),
            "items": list(obs.get("items", []) or []),
        })

    def render_distribution(self, obs: Dict[str, Any]) -> ReportNode:
        buckets = obs.get("buckets", {}) or {}
        rows = sorted(buckets.items(), key=lambda kv: (-kv[1], kv[0]))
        return ReportNode(type="distribution_table", data={
            "id":     obs.get("id", ""),
            "label":  obs.get("label", ""),
            "rows":   rows,
            "total":  sum(buckets.values()),
            "unique": len(buckets),
        })

    def render_histogram(self, obs: Dict[str, Any]) -> ReportNode:
        top = obs.get("top_n", []) or []
        return ReportNode(type="histogram_table", data={
            "id":     obs.get("id", ""),
            "label":  obs.get("label", ""),
            "rows":   [(p["key"], p["count"]) for p in top],
            "total":  obs.get("total", 0),
            "unique": obs.get("unique", 0),
        })

    # ── payload sub-dispatch ──────────────────────────────────────────

    def render_payload(self, obs: Dict[str, Any]) -> ReportNode:
        schema = obs.get("payload_schema", "?")
        method_map = {
            "html":               self.render_payload_html,
            "elements":           self.render_payload_table,
            "layered":            self.render_payload_table,
            "interactive":        self.render_payload_table,
            "screenshot":         self.render_payload_screenshot,
            "accessibility_tree": self.render_payload_accessibility,
            "dom_tree":           self.render_payload_dom_tree,
        }
        method = method_map.get(schema, self.render_payload_unknown)
        return method(obs)

    def render_payload_html(self, obs: Dict[str, Any]) -> ReportNode:
        data = obs.get("data") or {}
        html = data.get("html") or ""
        return ReportNode(type="html_excerpt", data={
            "id":     obs.get("id", ""),
            "label":  obs.get("label", ""),
            "url":    data.get("url"),
            "status": data.get("status"),
            "length": len(html),
            "html":   html,
        })

    def render_payload_table(self, obs: Dict[str, Any]) -> ReportNode:
        data = obs.get("data") or {}
        return ReportNode(type="record_table", data={
            "id":      obs.get("id", ""),
            "label":   obs.get("label", ""),
            "schema":  obs.get("payload_schema", "?"),
            "columns": list(data.get("columns") or []),
            "rows":    list(data.get("rows") or []),
        })

    def render_payload_screenshot(self, obs: Dict[str, Any]) -> ReportNode:
        data = obs.get("data") or {}
        node = ReportNode(type="image", data={
            "id":         obs.get("id", ""),
            "label":      obs.get("label", ""),
            "format":     data.get("format"),
            "width":      data.get("width"),
            "height":     data.get("height"),
            "size_bytes": data.get("size_bytes"),
            "sha256":     data.get("sha256"),
            "ref":        data.get("ref"),
            "mime_type":  data.get("mime_type", "image/png"),
        })
        # Asset reference; renderer resolves to bytes via asset_loader if it has one.
        if data.get("sha256"):
            node.attachments.append(Attachment(
                name=obs.get("label", "image"),
                mime_type=data.get("mime_type", "image/png"),
                asset_ref=dict(data),
            ))
        return node

    def render_payload_accessibility(self, obs: Dict[str, Any]) -> ReportNode:
        data = obs.get("data") or {}
        return ReportNode(type="accessibility", data={
            "id":     obs.get("id", ""),
            "label":  obs.get("label", ""),
            "format": data.get("format"),
            "raw":    data,
        })

    def render_payload_dom_tree(self, obs: Dict[str, Any]) -> ReportNode:
        data = obs.get("data") or {}
        return ReportNode(type="dom_tree", data={
            "id":             obs.get("id", ""),
            "label":          obs.get("label", ""),
            "root":           data.get("root"),
            "node_count":     data.get("node_count", 0),
            "kept_count":     data.get("kept_count", 0),
            "skipped_count":  data.get("skipped_count", 0),
            "filter":         data.get("filter"),
            "with_hierarchy": data.get("with_hierarchy", False),
            "skipped":        data.get("skipped") or [],
        })

    def render_payload_unknown(self, obs: Dict[str, Any]) -> ReportNode:
        return ReportNode(type="unknown_payload", data={
            "id":             obs.get("id", ""),
            "label":          obs.get("label", ""),
            "payload_schema": obs.get("payload_schema", "?"),
            "data_type":      type(obs.get("data")).__name__,
        })

    def _render_unknown_obs(self, obs: Dict[str, Any]) -> ReportNode:
        return ReportNode(type="unknown_obs", data={
            "id":    obs.get("id", ""),
            "label": obs.get("label", ""),
            "kind":  obs.get("kind", "?"),
        })

    # ── per-kind change dispatch ──────────────────────────────────────

    def render_change(self, obs_id: str, change: Dict[str, Any]) -> ReportNode:
        kind = change.get("kind")
        if kind == "added":
            return self.render_change_added(obs_id, change)
        if kind == "removed":
            return self.render_change_removed(obs_id, change)
        method = getattr(self, f"render_change_{kind}", None)
        if method:
            return method(obs_id, change)
        return ReportNode(type="change_unknown", data={
            "id": obs_id, "kind": kind, "raw": change,
        })

    def render_change_added(self, obs_id: str, change: Dict[str, Any]) -> ReportNode:
        return ReportNode(type="change_added", data={"id": obs_id})

    def render_change_removed(self, obs_id: str, change: Dict[str, Any]) -> ReportNode:
        return ReportNode(type="change_removed", data={"id": obs_id})

    def render_change_scalar(self, obs_id: str, change: Dict[str, Any]) -> ReportNode:
        return ReportNode(type="change_scalar", data={
            "id":     obs_id,
            "before": change.get("before"),
            "after":  change.get("after"),
            "delta":  change.get("delta"),
        })

    def render_change_boolean(self, obs_id: str, change: Dict[str, Any]) -> ReportNode:
        return ReportNode(type="change_boolean", data={
            "id":     obs_id,
            "before": change.get("before"),
            "after":  change.get("after"),
        })

    def render_change_rule_check(
        self, obs_id: str, change: Dict[str, Any],
    ) -> ReportNode:
        return ReportNode(type="change_rule", data={
            "id":                  obs_id,
            "transition":          change.get("transition"),
            "new_violations":      change.get("new_violations"),
            "new_sample":          change.get("new_sample") or [],
            "resolved_violations": change.get("resolved_violations"),
            "scope_before":        change.get("scope_before"),
            "scope_after":         change.get("scope_after"),
            "scope_delta":         change.get("scope_delta"),
        })

    def render_change_set(self, obs_id: str, change: Dict[str, Any]) -> ReportNode:
        return ReportNode(type="change_set", data={
            "id":      obs_id,
            "added":   change.get("added") or [],
            "removed": change.get("removed") or [],
        })

    def render_change_distribution(
        self, obs_id: str, change: Dict[str, Any],
    ) -> ReportNode:
        return ReportNode(type="change_distribution", data={
            "id":           obs_id,
            "added_keys":   change.get("added_keys") or [],
            "removed_keys": change.get("removed_keys") or [],
            "modified":     change.get("modified") or {},
        })

    def render_change_histogram(
        self, obs_id: str, change: Dict[str, Any],
    ) -> ReportNode:
        return ReportNode(type="change_histogram", data={
            "id":             obs_id,
            "total_before":   change.get("total_before"),
            "total_after":    change.get("total_after"),
            "unique_before":  change.get("unique_before"),
            "unique_after":   change.get("unique_after"),
        })

    def render_change_payload(
        self, obs_id: str, change: Dict[str, Any],
    ) -> ReportNode:
        return ReportNode(type="change_payload", data={
            "id":             obs_id,
            "payload_schema": change.get("payload_schema")
                              or change.get("payload_schema_after"),
            "raw":            change,
        })
