"""Kind-aware semantic diff for snapshot envelopes.

`diff_envelopes` compares two envelopes (each a dict with an `observations`
list) and returns a per-observation change report keyed by observation id.
Each change record carries a `kind` matching the source observation's kind,
so renderers can dispatch on it.
"""

from typing import Any, Dict, Optional

from dimensions.observation import (
    BOOLEAN,
    DISTRIBUTION,
    HISTOGRAM,
    PAYLOAD,
    RULE_CHECK,
    SCALAR,
    SET,
)


def diff_envelopes(
    baseline: Dict[str, Any],
    current: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    by_id_before = {
        o["id"]: o for o in baseline.get("observations", []) if "id" in o
    }
    by_id_after = {
        o["id"]: o for o in current.get("observations", []) if "id" in o
    }

    all_ids = sorted(set(by_id_before) | set(by_id_after))
    changes: Dict[str, Dict[str, Any]] = {}

    for oid in all_ids:
        change = diff_observation(by_id_before.get(oid), by_id_after.get(oid))
        if change is not None:
            changes[oid] = change

    return changes


def diff_observation(
    before: Optional[Dict[str, Any]],
    after: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if before is None and after is not None:
        return {"kind": "added", "to": after}
    if after is None and before is not None:
        return {"kind": "removed", "from": before}
    if before is None or after is None:
        return None

    kind = before.get("kind") or after.get("kind")

    if kind == SCALAR:
        b, a = before.get("value"), after.get("value")
        if b == a:
            return None
        try:
            delta: Optional[float] = a - b
        except (TypeError, ValueError):
            delta = None
        return {"kind": SCALAR, "before": b, "after": a, "delta": delta}

    if kind == BOOLEAN:
        b, a = before.get("value"), after.get("value")
        if b == a:
            return None
        return {"kind": BOOLEAN, "before": b, "after": a}

    if kind == RULE_CHECK:
        b_passed = before.get("passed")
        a_passed = after.get("passed")
        b_count = before.get("violations_count", 0)
        a_count = after.get("violations_count", 0)
        b_checked = before.get("checked_count")
        a_checked = after.get("checked_count")
        scope_changed = (
            b_checked is not None
            and a_checked is not None
            and b_checked != a_checked
        )
        if b_passed == a_passed and b_count == a_count and not scope_changed:
            return None
        change: Dict[str, Any] = {"kind": RULE_CHECK}
        if b_passed != a_passed:
            change["transition"] = f"{b_passed} → {a_passed}"
        if a_count > b_count:
            change["new_violations"] = a_count - b_count
            change["new_sample"] = after.get("violations_sample", [])[:5]
        elif a_count < b_count:
            change["resolved_violations"] = b_count - a_count
        if scope_changed:
            change["scope_before"] = b_checked
            change["scope_after"] = a_checked
            change["scope_delta"] = a_checked - b_checked
        return change

    if kind == SET:
        b_items = set(before.get("items", []))
        a_items = set(after.get("items", []))
        added = sorted(a_items - b_items)
        removed = sorted(b_items - a_items)
        if not added and not removed:
            return None
        return {"kind": SET, "added": added, "removed": removed}

    if kind == DISTRIBUTION:
        b_buckets = before.get("buckets", {})
        a_buckets = after.get("buckets", {})
        added_keys = sorted(set(a_buckets) - set(b_buckets))
        removed_keys = sorted(set(b_buckets) - set(a_buckets))
        modified = {}
        for k in set(b_buckets) & set(a_buckets):
            if b_buckets[k] != a_buckets[k]:
                try:
                    delta_v: Optional[float] = a_buckets[k] - b_buckets[k]
                except (TypeError, ValueError):
                    delta_v = None
                modified[k] = {
                    "before": b_buckets[k],
                    "after": a_buckets[k],
                    "delta": delta_v,
                }
        if not added_keys and not removed_keys and not modified:
            return None
        return {
            "kind": DISTRIBUTION,
            "added_keys": added_keys,
            "removed_keys": removed_keys,
            "modified": modified,
        }

    if kind == HISTOGRAM:
        b_total = before.get("total", 0)
        a_total = after.get("total", 0)
        b_unique = before.get("unique", 0)
        a_unique = after.get("unique", 0)
        b_top = {p["key"]: p["count"] for p in before.get("top_n", [])}
        a_top = {p["key"]: p["count"] for p in after.get("top_n", [])}
        if b_total == a_total and b_unique == a_unique and b_top == a_top:
            return None
        return {
            "kind": HISTOGRAM,
            "total_before": b_total,
            "total_after": a_total,
            "unique_before": b_unique,
            "unique_after": a_unique,
            "top_added": sorted(set(a_top) - set(b_top)),
            "top_removed": sorted(set(b_top) - set(a_top)),
        }

    if kind == PAYLOAD:
        return _diff_payload(before, after)

    if before != after:
        return {"kind": "raw", "before": before, "after": after}
    return None


# ── payload diff ──────────────────────────────────────────────────────────


def _diff_payload(
    before: Dict[str, Any], after: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Schema-aware diff for payload observations."""
    b_schema = before.get("payload_schema")
    a_schema = after.get("payload_schema")
    b_data = before.get("data")
    a_data = after.get("data")

    if b_schema != a_schema:
        return {
            "kind": PAYLOAD,
            "payload_schema_before": b_schema,
            "payload_schema_after": a_schema,
            "before": b_data,
            "after": a_data,
        }

    if b_data == a_data:
        return None

    schema = a_schema or b_schema

    # Screenshot: compare hash and size.
    if schema == "screenshot" and isinstance(b_data, dict) and isinstance(
        a_data, dict
    ):
        return _diff_screenshot(b_data, a_data)

    # Fallback: structural diff (covers `dom_tree` and any future schemas).
    return {
        "kind": PAYLOAD,
        "payload_schema": schema,
        "before": b_data,
        "after": a_data,
    }


def _diff_screenshot(
    before: Dict[str, Any], after: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    if before.get("sha256") == after.get("sha256"):
        return None
    return {
        "kind": PAYLOAD,
        "payload_schema": "screenshot",
        "sha256_before": before.get("sha256"),
        "sha256_after": after.get("sha256"),
        "size_before": before.get("size_bytes"),
        "size_after": after.get("size_bytes"),
        "width_before": before.get("width"),
        "width_after": after.get("width"),
        "height_before": before.get("height"),
        "height_after": after.get("height"),
    }
