"""Real-data diff between two captures, ready to render side-by-side.

This module supplies the comparators the new `render-diff` command uses:

* ``compute_screenshot_diff(baseline_bytes, current_bytes)`` — runs
  pixelmatch (the algorithm Playwright bundles for ``to_have_screenshot``)
  over two PNG byte arrays. Returns a metrics dict + a PNG overlay
  highlighting the changed pixels.

* ``compute_tree_diff(baseline_payload, current_payload)`` — compares two
  ``dom_tree`` payloads leaf-by-leaf using a path-key matcher. For each
  matched pair (and each ancestor along its chain) it produces a
  per-property delta list — the actual before/after values from the
  captured data, not summary stats.

The output is structured for direct consumption by a renderer; no
rendering decisions live here.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple


# ── screenshot diff (pixelmatch) ──────────────────────────────────────────


def compute_screenshot_diff(
    baseline_bytes: bytes,
    current_bytes: bytes,
    *,
    threshold: float = 0.1,
    include_aa: bool = False,
) -> Dict[str, Any]:
    """Pixel-by-pixel diff of two PNG byte arrays via pixelmatch.

    Parameters mirror Playwright's ``to_have_screenshot`` defaults:
    ``threshold=0.1`` (perceptual delta cutoff), ``include_aa=False``
    (anti-aliased pixels are skipped).

    Returns a dict with:
      * ``available``: True if both images loaded and matched in size
      * ``size_mismatch``: True when widths/heights differ (pixelmatch
        cannot run; only metadata returned)
      * ``width`` / ``height``: rendered dimensions
      * ``total_pixels``, ``diff_pixels``, ``percent_changed``
      * ``bbox``: [x, y, w, h] minimal box enclosing changes (None if no diff)
      * ``diff_image_bytes``: PNG bytes of the highlighted overlay, or None
    """
    try:
        from PIL import Image
        from pixelmatch.contrib.PIL import pixelmatch
    except ImportError:
        return {"available": False, "reason": "pixelmatch not installed"}

    a = Image.open(BytesIO(baseline_bytes)).convert("RGBA")
    b = Image.open(BytesIO(current_bytes)).convert("RGBA")
    size_mismatch = a.size != b.size
    size_before = a.size
    size_after  = b.size
    if size_mismatch:
        # Pad both to the union canvas so pixelmatch can still run.
        # Extra rows/columns that only exist on one side render as
        # solid changed pixels — accurate: those regions don't exist
        # on the other side.
        union_w = max(a.size[0], b.size[0])
        union_h = max(a.size[1], b.size[1])
        canvas_a = Image.new("RGBA", (union_w, union_h), (0, 0, 0, 0))
        canvas_b = Image.new("RGBA", (union_w, union_h), (0, 0, 0, 0))
        canvas_a.paste(a, (0, 0))
        canvas_b.paste(b, (0, 0))
        a, b = canvas_a, canvas_b
    overlay = Image.new("RGBA", a.size, (0, 0, 0, 0))
    diff_pixels = pixelmatch(
        a, b, output=overlay,
        threshold=threshold,
        includeAA=include_aa,
        diff_mask=False,   # paint over a faded baseline so the diff is in context
    )
    bbox = overlay.getbbox()
    total = a.size[0] * a.size[1]
    out_buf = BytesIO()
    overlay.save(out_buf, format="PNG")
    return {
        "available":         True,
        "width":             a.size[0],
        "height":            a.size[1],
        "total_pixels":      total,
        "diff_pixels":       int(diff_pixels),
        "percent_changed":   round(100.0 * diff_pixels / total, 4) if total else 0.0,
        "bbox":              list(bbox) if bbox else None,
        "diff_image_bytes":  out_buf.getvalue(),
        "size_mismatch":     size_mismatch,
        "size_before":       size_before,
        "size_after":        size_after,
    }


# ── tree diff ─────────────────────────────────────────────────────────────


# Properties compared per node. `bbox` is split into x/y/width/height; attrs
# and computed_style are dicts compared key-by-key downstream.
_DIRECT_KEYS = (
    "tag", "id", "role", "aria_label", "text",
    "position", "z_index", "visible",
)

# Minimal subset of fields shipped to the renderer (deltas already carry the
# actual property comparisons). Storing full ``computed_style`` + every
# ``attribute`` per node — for both baseline and current, repeated across
# every leaf's ancestor chain — explodes the JSON; the renderer only needs
# enough to label and identify each node visually.
_SUMMARY_KEYS = (
    "tag", "id", "classes", "role", "aria_label", "text",
    "x", "y", "width", "height",
)


def _summary(node: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if node is None:
        return None
    return {k: node.get(k) for k in _SUMMARY_KEYS}


def compute_tree_diff(
    baseline_payload: Dict[str, Any],
    current_payload:  Dict[str, Any],
) -> Dict[str, Any]:
    """Leaf-by-leaf real-data diff of two ``dom_tree`` payloads.

    Returns a dict of:

      * ``stats``  ``{total, unchanged, modified, added, removed}``
      * ``nodes``  Map keyed by path-key. Every node touched by either tree
                   gets exactly one entry: status, lean baseline/current
                   summaries, per-property deltas. Used as the canonical
                   record so the leaf list and ancestor chains can refer
                   to nodes by key without duplicating their data.
      * ``leaves`` List of ``{key, ancestor_keys: [...]}``. Each entry
                   names the leaf's path-key and the chain of ancestor
                   keys (innermost → root). The renderer looks both up
                   in ``nodes`` to get the diff records.
    """
    b_nodes = _flatten(baseline_payload.get("root"))
    c_nodes = _flatten(current_payload.get("root"))

    b_keys = _path_keys(b_nodes)
    c_keys = _path_keys(c_nodes)

    b_by_key = {b_keys[n["idx"]]: n for n in b_nodes}
    c_by_key = {c_keys[n["idx"]]: n for n in c_nodes}

    b_leaves = _leaves_with_ancestors(b_nodes)
    c_leaves = _leaves_with_ancestors(c_nodes)
    b_leaf_by_key = {b_keys[leaf["idx"]]: (leaf, anc) for leaf, anc in b_leaves}
    c_leaf_by_key = {c_keys[leaf["idx"]]: (leaf, anc) for leaf, anc in c_leaves}
    all_leaf_keys = sorted(set(b_leaf_by_key) | set(c_leaf_by_key))

    # Build the deduped node table — every key from either side gets one
    # record carrying its diff classification + deltas + summaries.
    all_keys = set(b_by_key) | set(c_by_key)
    nodes_table: Dict[str, Dict[str, Any]] = {}
    for key in all_keys:
        b_node = b_by_key.get(key)
        c_node = c_by_key.get(key)
        if b_node and c_node:
            deltas = _node_deltas(b_node, c_node, b_nodes, c_nodes)
            if deltas:
                nodes_table[key] = {
                    "status":   "modified",
                    "baseline": _summary(b_node),
                    "current":  _summary(c_node),
                    "deltas":   deltas,
                }
            else:
                # Unchanged: the two summaries are identical at every key
                # we'd ship — store just one. The renderer falls back to
                # ``baseline`` when ``current`` is missing, so either field
                # works as the canonical summary.
                nodes_table[key] = {
                    "status":  "unchanged",
                    "current": _summary(c_node),
                    "deltas":  [],
                }
        elif c_node:
            nodes_table[key] = {
                "status":  "added",
                "current": _summary(c_node),
                "deltas":  [],
            }
        else:
            nodes_table[key] = {
                "status":   "removed",
                "baseline": _summary(b_node),
                "deltas":   [],
            }

    # Each leaf record holds just its key + the ordered list of ancestor
    # keys (innermost → root). The renderer resolves both via `nodes`.
    leaves_diff: List[Dict[str, Any]] = []
    for key in all_leaf_keys:
        b_pair = b_leaf_by_key.get(key)
        c_pair = c_leaf_by_key.get(key)
        # Ancestor chain — pick whichever side has the leaf; for matched
        # leaves both sides carry the same path, so baseline is fine.
        if b_pair:
            anc_keys = [b_keys[a["idx"]] for a in b_pair[1]]
        elif c_pair:
            anc_keys = [c_keys[a["idx"]] for a in c_pair[1]]
        else:
            anc_keys = []
        leaves_diff.append({"key": key, "ancestors": anc_keys})

    # Stats are derived from the leaf entries via the node table.
    stats = {
        "total":     len(leaves_diff),
        "unchanged": sum(1 for l in leaves_diff if nodes_table[l["key"]]["status"] == "unchanged"),
        "modified":  sum(1 for l in leaves_diff if nodes_table[l["key"]]["status"] == "modified"),
        "added":     sum(1 for l in leaves_diff if nodes_table[l["key"]]["status"] == "added"),
        "removed":   sum(1 for l in leaves_diff if nodes_table[l["key"]]["status"] == "removed"),
    }
    return {"stats": stats, "nodes": nodes_table, "leaves": leaves_diff}


# ── tree-diff helpers ─────────────────────────────────────────────────────


def _flatten(root: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pre-order walk → flat list with `idx` + `parent` indices.

    Children references are dropped (we look up by parent_idx instead).
    """
    if root is None:
        return []
    out: List[Dict[str, Any]] = []

    def walk(n: Dict[str, Any], parent_idx: int) -> None:
        idx = len(out)
        view = {k: v for k, v in n.items() if k != "children"}
        view["idx"] = idx
        view["parent"] = parent_idx
        out.append(view)
        for child in (n.get("children") or []):
            walk(child, idx)

    walk(root, -1)
    return out


def _leaves_with_ancestors(
    nodes: List[Dict[str, Any]],
) -> List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    """Return [(leaf, [ancestor_innermost, ..., outermost])] for every leaf."""
    if not nodes:
        return []
    children_count = [0] * len(nodes)
    for n in nodes:
        if n["parent"] != -1:
            children_count[n["parent"]] += 1
    out: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    for n in nodes:
        if children_count[n["idx"]] == 0:
            anc = []
            cur = n
            while cur["parent"] != -1:
                cur = nodes[cur["parent"]]
                anc.append(cur)
            out.append((n, anc))
    return out


def _path_keys(nodes: List[Dict[str, Any]]) -> Dict[int, str]:
    """Compute a stable path key per node (root → … → self).

    Thin wrapper over `dimensions.uipath.derive_all` — the framework's
    canonical UIPath grammar. Key per level is ``tag[#id][:nth(N)]`` for
    legacy walks (no testid/role); richer captures get bracket selectors
    (``[testid=…]``, ``[role=…][name=…]``, ``[name=…]``) when those
    attributes are present. Classes are intentionally NOT part of
    identity so a class change shows up as a *modification* of the same
    node, not as a removed-and-added pair.
    """
    from dimensions.uipath import derive_all, format_uipath
    if not nodes:
        return {}
    paths = derive_all(nodes)
    return {idx: format_uipath(p) for idx, p in paths.items()}


def _path_keys_legacy(nodes: List[Dict[str, Any]]) -> Dict[int, str]:
    """Original implementation kept for the round-trip backwards-compat
    test only; not used at runtime. Removed in PR3+ once we're confident
    the UIPath wrapper produces identical output for legacy walks.
    """
    if not nodes:
        return {}

    children_by_parent: Dict[int, List[int]] = {}
    for n in nodes:
        children_by_parent.setdefault(n["parent"], []).append(n["idx"])

    own_key: Dict[int, str] = {}
    for n in nodes:
        k = n.get("tag", "?")
        if n.get("id"):
            k += "#" + str(n["id"])
        own_key[n["idx"]] = k

    nth: Dict[int, int] = {}
    for parent_idx, children in children_by_parent.items():
        groups: Dict[str, List[int]] = {}
        for c in children:
            groups.setdefault(own_key[c], []).append(c)
        for k, group in groups.items():
            if len(group) > 1:
                for pos, c in enumerate(group, 1):
                    nth[c] = pos

    keys: Dict[int, str] = {}
    for n in nodes:
        chain: List[str] = []
        cur_idx = n["idx"]
        while cur_idx != -1:
            tok = own_key[cur_idx]
            if cur_idx in nth:
                tok += f":nth({nth[cur_idx]})"
            chain.append(tok)
            cur_idx = nodes[cur_idx]["parent"]
        keys[n["idx"]] = ">".join(reversed(chain))
    return keys


def _effective_style(
    node: Dict[str, Any], all_nodes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Walk parent chain, merging delta computed_style values into the full
    effective style (parent → child order, child overrides)."""
    chain = [node]
    cur = node
    while cur["parent"] != -1:
        cur = all_nodes[cur["parent"]]
        chain.append(cur)
    out: Dict[str, Any] = {}
    for n in reversed(chain):
        cs = n.get("computed_style") or {}
        out.update(cs)
    return out


def _node_deltas(
    b: Dict[str, Any],
    c: Dict[str, Any],
    b_all: List[Dict[str, Any]],
    c_all: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compute the per-property delta list between two matched nodes."""
    deltas: List[Dict[str, Any]] = []

    for key in _DIRECT_KEYS:
        bv, cv = b.get(key), c.get(key)
        if bv != cv:
            deltas.append({"path": key, "before": bv, "after": cv})

    bcl = sorted(b.get("classes") or [])
    ccl = sorted(c.get("classes") or [])
    if bcl != ccl:
        deltas.append({"path": "classes", "before": bcl, "after": ccl})

    for key in ("x", "y", "width", "height"):
        bv, cv = b.get(key), c.get(key)
        if bv != cv:
            deltas.append({"path": f"bbox/{key}", "before": bv, "after": cv})

    b_attrs = b.get("attributes") or {}
    c_attrs = c.get("attributes") or {}
    for k in sorted(set(b_attrs) | set(c_attrs)):
        bv = b_attrs.get(k)
        cv = c_attrs.get(k)
        if bv != cv:
            deltas.append({"path": f"attr/{k}", "before": bv, "after": cv})

    b_eff = _effective_style(b, b_all)
    c_eff = _effective_style(c, c_all)
    for k in sorted(set(b_eff) | set(c_eff)):
        bv = b_eff.get(k)
        cv = c_eff.get(k)
        if bv == cv:
            continue
        if bv in (None, "", "auto", "normal") and cv in (None, "", "auto", "normal"):
            continue
        deltas.append({"path": f"css/{k}", "before": bv, "after": cv})

    return deltas



def _diff_ancestor_chain(
    b_anc: List[Dict[str, Any]],
    c_anc: List[Dict[str, Any]],
    b_keys: Dict[int, str],
    c_keys: Dict[int, str],
    b_by_key: Dict[str, Dict[str, Any]],
    c_by_key: Dict[str, Dict[str, Any]],
    b_all: List[Dict[str, Any]],
    c_all: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Walk ancestor chains in parallel (innermost → root), pairing by path key."""
    out: List[Dict[str, Any]] = []
    # Use a set of all ancestor keys from both sides, in chain order.
    seen_keys: set = set()
    chain_b_keys = [b_keys[a["idx"]] for a in b_anc]
    chain_c_keys = [c_keys[a["idx"]] for a in c_anc]
    # Take chain order from baseline first, then any current-only appended.
    ordered: List[str] = []
    for k in chain_b_keys + chain_c_keys:
        if k not in seen_keys:
            seen_keys.add(k)
            ordered.append(k)

    for key in ordered:
        b_node = b_by_key.get(key)
        c_node = c_by_key.get(key)
        if b_node and c_node:
            deltas = _node_deltas(b_node, c_node, b_all, c_all)
            out.append({
                "status":   "modified" if deltas else "unchanged",
                "baseline": _summary(b_node),
                "current":  _summary(c_node),
                "deltas":   deltas,
            })
        elif c_node:
            out.append({
                "status": "added", "baseline": None,
                "current": _summary(c_node), "deltas": [],
            })
        else:
            out.append({
                "status": "removed", "baseline": _summary(b_node),
                "current": None, "deltas": [],
            })
    return out
