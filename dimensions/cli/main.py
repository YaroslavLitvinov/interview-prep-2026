"""CLI commands for the dimensions framework.

Usage:
    python3 -m dimensions <DIMENSION|all> <command> [args]

Every command requires a leading scope token: either a registered
dimension name (``data``, ``visual``, …) or the literal ``all`` to
operate across every applicable dimension.

Commands:
    list                            List registered dimensions
    list-snapshots                  List saved labels
    schema                          Print the JSON Schema for the scoped envelope(s)
    inspect                         Live capture + render (no save)
    capture <label>                 Capture and persist a snapshot under <label>
    show <label>                    Render a saved snapshot as markdown
    report <label>                  Full markdown report for <label>
    diff <baseline> <current>       Render a markdown comparison between two snapshots

Examples:
    python3 -m dimensions all list
    python3 -m dimensions data inspect
    python3 -m dimensions all capture baseline
    python3 -m dimensions visual show baseline
    python3 -m dimensions data schema
    python3 -m dimensions data diff baseline current
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dimensions.config import DEFAULT_CONFIG_NAME
from dimensions.dimensions import Dimensions
from dimensions.kinds import KIND_REGISTRY
from dimensions.render import (
    render_comparison_markdown,
    render_envelope_markdown,
)
from dimensions.diff_render import compute_screenshot_diff, compute_tree_diff
from dimensions.render_schema import BaseRenderSchema
from dimensions.renderers import HtmlRenderer
from dimensions.schema.envelope import EnvelopeAdapter
from dimensions.validate import SnapshotValidationError


# Every command requires a scope token (``all`` or a specific dimension
# name). The scope makes the per-dimension nature of envelopes explicit
# in the CLI surface.
_DIM_COMMANDS = {
    "list",
    "list-snapshots",
    "schema",
    "inspect",
    "capture",
    "show",
    "report",
    "diff",
    "render-html",
    "render-md",
    "render-diff",
    "capture-to-fixture",
    "comment",
    "scenarios",
}

_GLOBAL_COMMANDS: set[str] = set()  # reserved for future non-dim ops, none today

# Reserved scope token meaning "every applicable dimension".
_ALL_SCOPE = "all"


# ── helpers ────────────────────────────────────────────────────────────────


def _build_dims(config_path: Path) -> Dimensions:
    return Dimensions(config_path)


def _print(s: str) -> None:
    print(s)


def _targets(dims: Dimensions, scoped_dim: Optional[str]) -> List[str]:
    """Return the list of dimensions a command should act on."""
    if scoped_dim:
        return [scoped_dim]
    return dims.list_known()


def _no_label_message(
    dims: Dimensions,
    scoped_dim: Optional[str],
    label: str,
    *,
    action_verb: str = "render",
) -> List[str]:
    """Build a user-friendly explanation when a label has no envelopes."""
    targets = _targets(dims, scoped_dim)
    available: List[str] = sorted({
        lbl for d in targets for lbl in dims.list_labels(d)
    })
    scope_token = scoped_dim or "all"
    out = [
        f"No snapshot found for label `{label}` "
        f"(dimension scope: `{scope_token}`).",
        "",
    ]
    if available:
        out.append(
            "Available labels: " + ", ".join(f"`{lbl}`" for lbl in available)
        )
        out.append(
            f"  Try: `python3 -m dimensions {scope_token} {action_verb} "
            f"{available[0]}`"
        )
    else:
        out.append(
            f"No snapshots have been captured yet. "
            f"Capture one first:"
        )
    out.append(
        f"  Capture: `python3 -m dimensions {scope_token} capture {label}`"
    )
    return out


# ── commands ───────────────────────────────────────────────────────────────


def cmd_list(args: argparse.Namespace) -> int:
    dims = _build_dims(Path(args.config))
    applicable = dims.applicable()
    if args.dim:
        applicable = [d for d in applicable if d.name == args.dim]
    if not applicable:
        _print("No dimensions registered." if not args.dim
               else f"Dimension `{args.dim}` is not applicable.")
        return 0
    _print("# Registered dimensions\n")
    for d in applicable:
        _print(f"## `{d.name}` (category: `{d.category}`)\n")
        if d.description:
            _print(d.description)
            _print("")
    return 0


def cmd_list_snapshots(args: argparse.Namespace) -> int:
    dims = _build_dims(Path(args.config))
    targets = _targets(dims, args.dim)
    _print("# Saved snapshots\n")
    for name in targets:
        labels = dims.list_labels(name)
        _print(f"## `{name}`\n")
        if labels:
            for label in labels:
                envs = dims.list_envelopes(name, label)
                _print(f"- `{label}` — {len(envs)} envelope(s): " +
                       ", ".join(f"`{e}`" for e in envs))
        else:
            _print("_(no snapshots)_")
        _print("")
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    """Print the JSON Schema for the scoped envelope(s).

    With a specific dimension scope, prints just that dimension's envelope
    schema. With ``all``, prints the discriminated union over every
    registered dimension.
    """
    from pydantic import TypeAdapter
    if args.dim is None:
        schema = EnvelopeAdapter.json_schema()
    else:
        spec = KIND_REGISTRY.get(args.dim)
        if spec is None:
            print(f"error: unknown dimension `{args.dim}`", file=sys.stderr)
            return 2
        schema = TypeAdapter(spec["envelope_cls"]).json_schema()
    _print(json.dumps(schema, indent=2))
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    dims = _build_dims(Path(args.config))
    results = asyncio.run(dims.collect(dimension_name=args.dim))
    if not results:
        target = args.dim or "(any)"
        _print(f"_No applicable dimension matched `{target}`._")
        return 1
    total = sum(len(r.envelopes) for r in results.values())
    _print(f"# Live inspection ({len(results)} dimension(s), {total} envelope(s))\n")
    for dim_name, result in results.items():
        loader = lambda sha, _r=result: _r.pending_assets[sha][0]
        for env in result.envelopes:
            _print(render_envelope_markdown(env, asset_loader=loader))
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    """Run every discovered scenario under a single user-chosen label.

    Test cases are sourced exclusively from ``tests/scenarios/`` (or
    whatever ``scenario_roots`` declares). The ``urls:`` block in
    ``dimensions.config.yaml`` is **not** a list of capture targets —
    it's a named host catalog consumed via ``${name}`` substitution
    inside scenario fixtures.

    Envelope names are namespaced as ``<scenario>.<env>`` so multiple
    scenarios coexist under one label without colliding.
    """
    from dimensions.config import Config
    from dimensions.testing import (
        UnresolvedScenarioVar, discover, resolve_scenario_urls,
    )

    cfg = Config.from_file(Path(args.config))
    dims = _build_dims(Path(args.config))
    plugin_classes = cfg.plugin_classes()
    plugin_cfgs = {
        e.get("name"): dict(e.get("config") or {}) for e in cfg.plugins
    }
    paths_by_key = _scenario_paths(cfg.scenario_roots)

    scenarios = discover(roots=cfg.scenario_roots)
    if args.dim:
        scenarios = [s for s in scenarios if s.plugin == args.dim]

    if not scenarios:
        _print(
            "No scenarios discovered. Add JSON files under "
            f"{cfg.scenario_roots!r} (e.g. tests/scenarios/visual/<name>.json)."
        )
        return 1

    _print(f"Capturing label `{args.label}` from {len(scenarios)} scenario(s):")
    failures = 0
    for s in scenarios:
        plugin_cls = plugin_classes.get(s.plugin)
        if plugin_cls is None:
            _print(
                f"  ⚠️  {s.plugin}/{s.name}: plugin not registered "
                f"({sorted(plugin_classes)})"
            )
            failures += 1
            continue
        try:
            resolved = resolve_scenario_urls(s, cfg.plugin_urls(s.plugin))
        except UnresolvedScenarioVar as exc:
            _print(f"  ❌ {s.plugin}/{s.name}: {exc}")
            failures += 1
            continue
        try:
            envs = _run_and_persist_scenario(
                resolved, plugin_cls, dims, plugin_cfgs.get(s.plugin, {}),
                label=args.label,
                source_path=paths_by_key.get((s.plugin, s.name)),
                namespace_envelopes=True,
            )
        except Exception as exc:  # noqa: BLE001
            _print(f"  ❌ {s.plugin}/{s.name}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        _print(f"  ✅ {s.plugin}/{s.name}: {envs} envelope(s)")

    return 0 if failures == 0 else 1


def cmd_show(args: argparse.Namespace) -> int:
    dims = _build_dims(Path(args.config))
    targets = _targets(dims, args.dim)
    parts: List[str] = [f"# Snapshot: `{args.label}`\n"]
    found_any = False
    for name in targets:
        if not dims.exists(name, args.label):
            parts.append(f"## `{name}`\n\n_(no snapshot saved as `{args.label}`)_\n")
            continue
        loader = lambda sha, _d=name, _l=args.label: dims.read_asset(_d, _l, sha)
        for env_name in dims.list_envelopes(name, args.label):
            try:
                envelope = dims.load(name, args.label, env_name)
            except SnapshotValidationError as e:
                parts.append(f"## `{name}/{env_name}`\n\n❌ Validation error: {e}\n")
                continue
            parts.append(render_envelope_markdown(envelope, asset_loader=loader))
            found_any = True
    _print("\n".join(parts))
    return 0 if found_any else 1


def cmd_report(args: argparse.Namespace) -> int:
    """Full report — every dimension × envelope rendered as markdown."""
    return cmd_show(args)


def cmd_render_md(args: argparse.Namespace) -> int:
    """Emit one markdown file per envelope, plus an index.md.

    Layout (default ``--out dimensions-reports/<dim>/<label>/``):
        <out>/<envelope>.md
        <out>/index.md
        <out>/assets/<sha>.<ext>     ← copied from snapshot's assets/

    Screenshots reference assets by relative path (lightweight markdown).
    Pass ``--inline-assets`` to embed image bytes as base64 data URLs
    (single self-contained file, no asset directory).
    """
    import shutil
    dims = _build_dims(Path(args.config))
    targets = _targets(dims, args.dim)
    written = 0
    for name in targets:
        if not dims.exists(name, args.label):
            continue
        out_dir = Path(args.out) / name / args.label
        out_dir.mkdir(parents=True, exist_ok=True)
        env_names = dims.list_envelopes(name, args.label)

        if not args.inline_assets:
            assets_src = dims.backend._assets_dir(name, args.label)
            if assets_src.is_dir():
                assets_dst = out_dir / "assets"
                assets_dst.mkdir(exist_ok=True)
                for p in assets_src.iterdir():
                    if p.is_file():
                        shutil.copy2(p, assets_dst / p.name)

        loader = (
            (lambda sha, _d=name, _l=args.label: dims.read_asset(_d, _l, sha))
            if args.inline_assets else None
        )
        index_links: List[str] = []
        for env_name in env_names:
            try:
                envelope = dims.load(name, args.label, env_name)
            except SnapshotValidationError as e:
                print(f"✗ {name}/{env_name}: {e}", file=sys.stderr)
                continue
            md = render_envelope_markdown(
                envelope,
                asset_loader=loader,
                inline_assets=args.inline_assets,
            )
            (out_dir / f"{env_name}.md").write_text(md)
            index_links.append(f"- [{env_name}]({env_name}.md)")
            written += 1

        if index_links:
            (out_dir / "index.md").write_text(
                f"# {name} / {args.label}\n\n" + "\n".join(index_links) + "\n"
            )

    if not written:
        for line in _no_label_message(
            dims, args.dim, args.label, action_verb="render-md",
        ):
            _print(line)
        return 1
    _print(f"✓ wrote {written} markdown file(s) → {Path(args.out)}")
    return 0


def cmd_render_diff(args: argparse.Namespace) -> int:
    """Emit per-envelope side-by-side diff reports between two labels.

    Output (default ``--out dimensions-reports``):
        <out>/<dim>/<baseline>.vs.<current>/
            <env>.diff.html
            assets/<sha>.png    ← baseline + current screenshots + pixelmatch overlays
            index.html
    """
    import shutil
    import hashlib
    import json as _json

    dims = _build_dims(Path(args.config))
    targets = _targets(dims, args.dim)
    out = Path(args.out)
    schema = BaseRenderSchema()
    written = 0

    for dim_name in targets:
        if not (
            dims.exists(dim_name, args.baseline)
            and dims.exists(dim_name, args.current)
        ):
            continue

        out_dir = out / dim_name / f"{args.baseline}.vs.{args.current}"
        out_dir.mkdir(parents=True, exist_ok=True)
        assets_dst = out_dir / "assets"
        assets_dst.mkdir(exist_ok=True)

        b_envs = set(dims.list_envelopes(dim_name, args.baseline))
        c_envs = set(dims.list_envelopes(dim_name, args.current))
        common = sorted(b_envs & c_envs)

        index_links: List[str] = []
        for env_name in common:
            try:
                b_env = dims.load(dim_name, args.baseline, env_name)
                c_env = dims.load(dim_name, args.current, env_name)
            except SnapshotValidationError as e:
                print(f"✗ {dim_name}/{env_name}: {e}", file=sys.stderr)
                continue
            # Tag each envelope with its label for the renderer.
            b_env["label"] = args.baseline
            c_env["label"] = args.current

            screenshot_assets, tree_data = _compute_envelope_diff(
                dims, dim_name, args.baseline, args.current, env_name,
                b_env, c_env, assets_dst,
            )
            if screenshot_assets is None and tree_data is None:
                continue   # nothing diffable in this envelope

            ir = schema.render_envelope_diff(
                b_env, c_env,
                screenshot_diff_assets=screenshot_assets,
                tree_diff_data=tree_data,
            )
            # Comments anchored to either side's snapshot apply to the diff
            # report. Merge sidecars from both labels so reviewers see the
            # full thread on the comparison page.
            from dimensions.comments import load_comments as _load_c
            diff_comments: List[Dict[str, Any]] = []
            for lbl in (args.baseline, args.current):
                try:
                    entries = _load_c(dims.backend._label_dir(dim_name, lbl))
                    diff_comments.extend(
                        e.model_dump(mode="json") for e in entries
                    )
                except Exception:
                    pass
            html = HtmlRenderer(
                title=f"diff · {dim_name} / {env_name} · "
                      f"{args.baseline} → {args.current}",
                comments=diff_comments,
                report_identity={
                    "dimension":     dim_name,
                    "envelope_name": env_name,
                    "labels":        [args.baseline, args.current],
                    "kind":          "diff",
                    "api_base":      getattr(args, "api_base", None),
                },
            ).render(ir)
            (out_dir / f"{env_name}.diff.html").write_text(html)
            index_links.append(
                f'<li><a href="{env_name}.diff.html">{env_name}</a></li>'
            )
            written += 1

        if index_links:
            (out_dir / "index.html").write_text(
                "<!doctype html><html lang=en><head><meta charset=utf-8>"
                "<meta name=viewport content='width=device-width,initial-scale=1'>"
                f"<title>{dim_name} · {args.baseline} → {args.current}</title>"
                "<style>body{font:16px/1.5 sans-serif;max-width:600px;"
                "margin:2rem auto;padding:1rem}a{color:#2563eb}</style>"
                f"</head><body><h1>{dim_name} · diff</h1>"
                f"<p>{args.baseline} → {args.current}</p>"
                f"<ul>{''.join(index_links)}</ul></body></html>"
            )

    if not written:
        for line in _no_label_message(
            dims, args.dim, args.baseline, action_verb="render-diff",
        ):
            _print(line)
        return 1
    _print(f"✓ wrote {written} diff file(s) → {Path(args.out)}")
    return 0


def _compute_envelope_diff(
    dims: Dimensions,
    dim_name: str,
    baseline_label: str,
    current_label: str,
    env_name: str,
    b_env: Dict[str, Any],
    c_env: Dict[str, Any],
    assets_dst: Path,
):
    """Compute screenshot- and tree-diff data for one envelope.

    Copies referenced screenshot assets into ``assets_dst`` and writes the
    pixelmatch overlay there. Returns (screenshot_diff_assets, tree_data),
    either may be None when the envelope doesn't carry that payload.
    """
    import hashlib
    import shutil

    def _payloads(env, schema):
        return [
            o for o in env.get("observations", [])
            if o.get("kind") == "payload" and o.get("payload_schema") == schema
        ]

    screenshot_assets = None
    b_shots = _payloads(b_env, "screenshot")
    c_shots = _payloads(c_env, "screenshot")
    if b_shots and c_shots:
        b_data = b_shots[0].get("data") or {}
        c_data = c_shots[0].get("data") or {}
        b_sha = b_data.get("sha256")
        c_sha = c_data.get("sha256")
        baseline_ref = current_ref = None
        diff_ref = None
        metrics: Dict[str, Any] = {"available": False}
        if b_sha and c_sha:
            try:
                b_bytes = dims.read_asset(dim_name, baseline_label, b_sha)
                c_bytes = dims.read_asset(dim_name, current_label, c_sha)
            except Exception:
                b_bytes = c_bytes = None
            if b_bytes and c_bytes:
                # Copy baseline + current images into the report's asset dir
                # using a label-prefixed sha so they don't collide.
                b_name = f"{baseline_label}-{b_sha}{Path(b_data.get('ref','')).suffix or '.png'}"
                c_name = f"{current_label}-{c_sha}{Path(c_data.get('ref','')).suffix or '.png'}"
                (assets_dst / b_name).write_bytes(b_bytes)
                (assets_dst / c_name).write_bytes(c_bytes)
                baseline_ref = f"assets/{b_name}"
                current_ref = f"assets/{c_name}"
                metrics = compute_screenshot_diff(b_bytes, c_bytes)
                diff_bytes = metrics.pop("diff_image_bytes", None)
                if diff_bytes:
                    diff_sha = hashlib.sha256(diff_bytes).hexdigest()[:16]
                    diff_name = f"diff-{baseline_label}-{current_label}-{diff_sha}.png"
                    (assets_dst / diff_name).write_bytes(diff_bytes)
                    diff_ref = f"assets/{diff_name}"
        screenshot_assets = {
            "baseline_ref": baseline_ref,
            "current_ref":  current_ref,
            "diff_ref":     diff_ref,
            "metrics":      metrics,
        }

    tree_data = None
    b_trees = _payloads(b_env, "dom_tree")
    c_trees = _payloads(c_env, "dom_tree")
    if b_trees and c_trees:
        tree_data = compute_tree_diff(
            b_trees[0].get("data") or {},
            c_trees[0].get("data") or {},
        )
        tree_data["envelope_name"] = env_name

    return screenshot_assets, tree_data


def cmd_render_html(args: argparse.Namespace) -> int:
    """Emit one self-contained HTML file per envelope, plus an index.html.

    Layout (default ``--out dimensions-reports/<dim>/<label>/``):
        <out>/<envelope>.html
        <out>/index.html
        <out>/assets/<sha>.<ext>     ← copied from snapshot's assets/

    Tables virtualise via embedded JSON; screenshots reference assets
    by relative path (lightweight HTML). Pass ``--inline-assets`` to
    embed image bytes as base64 data URLs (single self-contained file).
    """
    import shutil
    dims = _build_dims(Path(args.config))
    targets = _targets(dims, args.dim)
    schema = BaseRenderSchema()
    written = 0
    for name in targets:
        if not dims.exists(name, args.label):
            continue
        out_dir = Path(args.out) / name / args.label
        out_dir.mkdir(parents=True, exist_ok=True)
        env_names = dims.list_envelopes(name, args.label)

        # Copy referenced assets unless inlining (so relative srcs resolve).
        if not args.inline_assets:
            assets_src = dims.backend._assets_dir(name, args.label)
            if assets_src.is_dir():
                assets_dst = out_dir / "assets"
                assets_dst.mkdir(exist_ok=True)
                for p in assets_src.iterdir():
                    if p.is_file():
                        shutil.copy2(p, assets_dst / p.name)

        loader = (
            (lambda sha, _d=name, _l=args.label: dims.read_asset(_d, _l, sha))
            if args.inline_assets else None
        )
        from dimensions.comments import load_comments as _load_c
        try:
            label_comments = [
                e.model_dump(mode="json")
                for e in _load_c(dims.backend._label_dir(name, args.label))
            ]
        except Exception:
            label_comments = []
        # Group envelopes by scenario prefix so .tree + .screenshot
        # for the same scenario land in a single HTML page.
        groups: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
        for env_name in env_names:
            try:
                envelope = dims.load(name, args.label, env_name)
            except SnapshotValidationError as e:
                print(f"✗ {name}/{env_name}: {e}", file=sys.stderr)
                continue
            group_key = _envelope_group_key(envelope, env_name)
            groups.setdefault(group_key, []).append((env_name, envelope))

        index_rows: List[Dict[str, Any]] = []
        for group_key, items in groups.items():
            irs = [schema.render_envelope(e) for _, e in items]
            html = HtmlRenderer(
                asset_loader=loader,
                inline_assets=args.inline_assets,
                title=f"{name} / {args.label} / {group_key}",
                comments=label_comments,
                report_identity={
                    "dimension":     name,
                    "label":         args.label,
                    "envelope_name": group_key,
                    "kind":          "snapshot",
                    "api_base":      getattr(args, "api_base", None),
                },
            ).render_many(irs)
            (out_dir / f"{group_key}.html").write_text(html)

            # Pull test result from whichever envelope carries it.
            result = None
            scenario = None
            for _, env in items:
                if result is None:
                    result = _envelope_test_result(env)
                if scenario is None:
                    scenario = (env.get("provenance") or {}).get("name")
            index_rows.append({
                "env_name": group_key,
                "result":   result,
                "scenario": scenario,
            })
            written += 1

        if index_rows:
            (out_dir / "index.html").write_text(
                _build_label_index_html(name, args.label, index_rows)
            )

    if not written:
        for line in _no_label_message(
            dims, args.dim, args.label, action_verb="render-html",
        ):
            _print(line)
        return 1
    _print(f"✓ wrote {written} HTML file(s) → {Path(args.out)}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    dims = _build_dims(Path(args.config))
    report = dims.compare(args.baseline, args.current)
    if args.dim:
        report = {k: v for k, v in report.items() if k == args.dim}
    parts: List[str] = [
        f"# Comparison: `{args.baseline}` → `{args.current}`\n",
    ]
    for dim_name, dim_report in report.items():
        added = dim_report.get("added_envelopes") or []
        removed = dim_report.get("removed_envelopes") or []
        if added or removed:
            parts.append(f"## `{dim_name}` — envelope set changed\n")
            if added:
                parts.append("- **Added envelopes:** " + ", ".join(f"`{n}`" for n in added))
            if removed:
                parts.append("- **Removed envelopes:** " + ", ".join(f"`{n}`" for n in removed))
            parts.append("")
        for env_name, result in dim_report.get("envelopes", {}).items():
            if "error" in result:
                parts.append(f"## `{dim_name}/{env_name}`\n\n_(error: {result['error']})_\n")
                continue
            parts.append(
                render_comparison_markdown(
                    f"{dim_name}/{env_name}",
                    result["changes"],
                    decisions=result.get("decisions", {}),
                )
            )
    _print("\n".join(parts))
    return 0


# ── dispatch ───────────────────────────────────────────────────────────────


def _extract_scope_token(argv: List[str]) -> tuple[Optional[str], List[str]]:
    """Pull the scope token (``all`` or a dimension name) from `argv`.

    Rules:
      - For commands in ``_DIM_COMMANDS``, the first non-flag positional MUST
        be a scope token; this function returns it.
      - For commands in ``_GLOBAL_COMMANDS``, no scope token is allowed.
      - In either case the function returns ``(scope_or_None, remaining_argv)``.

    Errors (missing scope on a dim command, or a stray scope on a global
    command) raise SystemExit with a helpful message.
    """
    out = list(argv)
    i = 0
    while i < len(out):
        tok = out[i]
        if tok.startswith("-"):
            if tok in {"--config"} and i + 1 < len(out):
                i += 2
                continue
            i += 1
            continue
        # First positional.
        if tok in _GLOBAL_COMMANDS:
            return None, out
        if tok in _DIM_COMMANDS:
            sys.stderr.write(
                f"error: `{tok}` requires a scope. "
                f"Prefix it with `all` or a dimension name "
                f"(e.g. `dimensions all {tok}` or `dimensions data {tok}`).\n"
            )
            raise SystemExit(2)
        # Treat as a scope token; the next positional should be the command.
        scope = tok
        rest = out[:i] + out[i + 1:]
        # Validate that what follows is actually a dim command.
        next_cmd = next(
            (t for t in rest[i:] if not t.startswith("-")), None
        )
        if next_cmd is None or next_cmd not in _DIM_COMMANDS:
            sys.stderr.write(
                f"error: `{scope}` is not a known command and the next "
                "token isn't a dimensional command. "
                f"Expected: dimensions <{_ALL_SCOPE}|DIMENSION> <command>.\n"
            )
            raise SystemExit(2)
        return scope, rest
    return None, out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dimensions")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_NAME,
        help="Path to dimensions.config.yaml (default: %(default)s)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List registered dimensions")
    sub.add_parser(
        "list-snapshots", help="List saved snapshots (scoped if a dimension prefix is given)"
    )
    sub.add_parser("schema", help="Print envelope JSON Schema")
    sub.add_parser(
        "inspect",
        help="Live capture + render to markdown (no save)",
    )

    p_capture = sub.add_parser(
        "capture", help="Capture and persist a snapshot under a label"
    )
    p_capture.add_argument("label")

    p_show = sub.add_parser(
        "show",
        help="Render a saved snapshot as markdown",
    )
    p_show.add_argument("label")

    p_report = sub.add_parser(
        "report",
        help="Full markdown report for a label",
    )
    p_report.add_argument("label")

    p_diff = sub.add_parser(
        "diff", help="Render a markdown comparison between two snapshots"
    )
    p_diff.add_argument("baseline")
    p_diff.add_argument("current")

    p_md = sub.add_parser(
        "render-md",
        help="Emit one markdown file per envelope (assets copied alongside)",
    )
    p_md.add_argument("label")
    p_md.add_argument(
        "--out",
        default="dimensions-reports",
        help="Output directory (default: %(default)s)",
    )
    p_md.add_argument(
        "--inline-assets",
        action="store_true",
        help=(
            "Embed image bytes inline as base64 data URLs. Off by default — "
            "screenshots reference `assets/<sha>.<ext>` (the framework copies "
            "the assets directory next to the rendered markdown so refs resolve)."
        ),
    )

    p_render_diff = sub.add_parser(
        "render-diff",
        help="Side-by-side diff report between two labels (HTML, per envelope)",
    )
    p_render_diff.add_argument("baseline")
    p_render_diff.add_argument("current")
    p_render_diff.add_argument(
        "--out",
        default="dimensions-reports",
        help="Output directory (default: %(default)s)",
    )
    p_render_diff.add_argument(
        "--api-base", default=None,
        help=(
            "Absolute base URL for the comments API (e.g. "
            "http://localhost:8765). Default: same-origin — works when "
            "the report is served by `dimensions.comments_server` on "
            "whatever host:port you ran it under."
        ),
    )

    p_html = sub.add_parser(
        "render-html",
        help="Emit lightweight, mobile-first HTML report(s) for a label",
    )
    p_html.add_argument("label")
    p_html.add_argument(
        "--out",
        default="dimensions-reports",
        help="Output directory (default: %(default)s)",
    )
    p_html.add_argument(
        "--inline-assets",
        action="store_true",
        help=(
            "Embed image bytes inline as base64 data URLs. Off by default — "
            "screenshots reference `assets/<sha>.<ext>` (the framework copies "
            "the assets directory next to the rendered HTML so refs resolve)."
        ),
    )
    p_html.add_argument(
        "--api-base", default=None,
        help=(
            "Absolute base URL for the comments API (e.g. "
            "http://localhost:8765). Default: same-origin."
        ),
    )

    p_fix = sub.add_parser(
        "capture-to-fixture",
        help="Convert a captured snapshot envelope into a compact "
             "UIPath-keyed fixture JSON",
    )
    p_fix.add_argument("label", help="Snapshot label to read from")
    p_fix.add_argument("envelope",
        help="Envelope name to convert (e.g. home.tree)")
    p_fix.add_argument(
        "--out", default=None,
        help="Output path. Default: tests/scenarios/<dim>/<name>.json",
    )
    p_fix.add_argument(
        "--name", default=None,
        help="Scenario name (defaults to <label>_<envelope>)",
    )
    p_fix.add_argument(
        "--trim", default="meaningful",
        choices=("all", "meaningful", "text-only"),
        help="Filter for which nodes appear in the fixture's dom_walk",
    )

    p_scn = sub.add_parser(
        "scenarios",
        help=(
            "List discovered scenarios. Running them is the job of "
            "`capture <label>` — scenarios are the test cases; the "
            "label is just where the captured envelopes are persisted."
        ),
    )
    p_scn.add_argument(
        "scenario_action", choices=("list",),
        help="list: print every discovered scenario as `<plugin>/<name>`",
    )

    p_comment = sub.add_parser(
        "comment",
        help="Add / resolve / list comments on a snapshot label",
    )
    p_comment.add_argument(
        "comment_action", choices=("add", "resolve", "list"),
    )
    p_comment.add_argument("label")
    p_comment.add_argument(
        "--envelope", default="main",
        help="Envelope name the comment targets (default: main)",
    )
    p_comment.add_argument(
        "--entity-id", default=None,
        help=(
            "entity_id of the observation being commented on. Omit to "
            "comment on the report itself."
        ),
    )
    p_comment.add_argument(
        "--author", default="anonymous",
        help="Author name for the comment (default: anonymous)",
    )
    p_comment.add_argument(
        "--text", default="",
        help="Comment body (required for add/resolve)",
    )
    p_comment.add_argument(
        "--resolution", choices=("approved", "denied"),
        help="For action=resolve only — approval decision",
    )

    return parser


def cmd_scenarios(args: argparse.Namespace) -> int:
    """List every discovered scenario as ``<plugin>/<name>``."""
    from dimensions.config import Config
    from dimensions.testing import discover

    cfg = Config.from_file(Path(args.config))
    scenarios = discover(roots=cfg.scenario_roots)
    if args.dim:
        scenarios = [s for s in scenarios if s.plugin == args.dim]
    for s in scenarios:
        print(f"{s.plugin}/{s.name}")
    return 0


def _run_and_persist_scenario(
    scenario, plugin_class, dims: Dimensions, plugin_cfg: Dict[str, Any],
    *,
    label: Optional[str] = None,
    source_path: Optional[Path] = None,
    namespace_envelopes: bool = False,
) -> int:
    """Run a scenario through the plugin's real protocol (Playwright for
    visual), then evaluate ``scenario.tests`` against the captured walk.
    """
    from dimensions.dimension import Dimension
    from dimensions.testing import evaluate_tests
    from dimensions.validate import validate_envelope

    # Build the plugin from config, overriding `urls` so the only URL
    # captured is the one declared in the scenario. Everything else
    # (viewport, timeout, wait policy, …) flows through unchanged.
    kwargs = dict(plugin_cfg)
    kwargs["urls"] = {"main": scenario.url}
    # Wait for every test target to appear before capturing — the
    # scenario already names what must be present, so re-purposing
    # those UIPaths as Playwright readiness signals is free.
    scenario_waits = _wait_selectors_from_tests(scenario)
    if scenario_waits:
        existing = kwargs.get("wait_for_selector")
        if existing:
            if isinstance(existing, str):
                kwargs["wait_for_selector"] = [existing, *scenario_waits]
            else:
                kwargs["wait_for_selector"] = [*existing, *scenario_waits]
        else:
            kwargs["wait_for_selector"] = scenario_waits
    plugin = plugin_class(**kwargs)
    dimension = Dimension(plugin, name=scenario.plugin)
    result = asyncio.run(dimension.collect())

    nonempty = [e for e in result.envelopes if e.get("observations")]

    provenance = {
        "kind":   "scenario",
        "name":   scenario.name,
        "plugin": scenario.plugin,
    }
    if source_path is not None:
        try:
            provenance["path"] = str(source_path.relative_to(Path.cwd()))
        except ValueError:
            provenance["path"] = str(source_path)

    # Evaluate `tests` against the live captured walk, then attach the
    # results as observations on the primary (tree) envelope.
    evaluation = evaluate_tests(scenario, nonempty)
    primary = _pick_primary_envelope(nonempty)
    if primary is not None:
        _attach_test_evidence(primary, evaluation, scenario)
        validate_envelope(primary)

    label = label if label is not None else scenario.name
    for envelope in nonempty:
        env_name = envelope["envelope_name"]
        if namespace_envelopes:
            env_name = f"{scenario.name}.{env_name}"
            envelope["envelope_name"] = env_name
        envelope["provenance"] = dict(provenance)
        dims.backend.save(scenario.plugin, label, env_name, envelope)
    for sha, (content, ext, _mime) in result.pending_assets.items():
        dims.backend.save_asset(scenario.plugin, label, sha, ext, content)
    return len(nonempty)


def _pick_primary_envelope(envelopes):
    """Pick the envelope the scenario assertion observations attach to.

    Prefer the tree envelope (`*.tree`); fall back to the first non-empty.
    """
    for env in envelopes:
        if (env.get("envelope_name") or "").endswith(".tree"):
            return env
    return envelopes[0] if envelopes else None


def _attach_test_evidence(envelope, evaluation, scenario):
    """Append rule_check observations capturing test results.

    - one ``scenario.test.<name>`` per test in ``scenario.tests``
    - one ``scenario.assertions`` rollup across all tests
    - one ``scenario.target_stability`` distribution (STRONG/MEDIUM/WEAK)
    """
    obs = envelope.setdefault("observations", [])

    for t in evaluation["tests"]:
        violations_sample = [
            c["detail"] or f"{c['uipath']} {c['detail']}"
            for c in t["checks"] if not c["passed"]
        ][:10]
        obs.append({
            "id":                f"scenario.test.{t['name']}",
            "kind":              "rule_check",
            "label":             f"Test `{t['name']}` (scenario `{scenario.name}`)",
            "passed":            t["passed"],
            "checked_count":     t["checked"],
            "violations_count":  len(t["violations"]),
            "violations_sample": violations_sample,
        })

    obs.append({
        "id":                "scenario.assertions",
        "kind":              "rule_check",
        "label":             f"All tests passed for scenario `{scenario.name}`",
        "passed":            evaluation["passed"],
        "checked_count":     evaluation["checked"],
        "violations_count":  len(evaluation["violations"]),
        "violations_sample": list(evaluation["violations"])[:10],
    })

    stab = evaluation["stability"]
    if any(stab.values()):
        obs.append({
            "id":      "scenario.target_stability",
            "kind":    "distribution",
            "label":   "Test target stability tiers",
            "buckets": {k: v for k, v in stab.items() if v},
        })


def _wait_selectors_from_tests(scenario) -> List[str]:
    """Derive a list of Playwright/CSS selectors from scenario.tests
    UIPaths, so capture waits for every target element to be visible
    before grabbing the screenshot.

    Uses only the LAST segment of each UIPath — the strongest anchor
    (testid / id) is enough for "wait until present". Falls back to
    the leaf tag if no strong anchor exists.
    """
    from dimensions.uipath import parse
    from dimensions.uipath.grammar import SelectorKind

    out: List[str] = []
    seen: set = set()
    for assertions in (scenario.tests or {}).values():
        for uipath_str in assertions.keys():
            try:
                p = parse(uipath_str)
            except Exception:  # noqa: BLE001
                continue
            if not p.segments:
                continue
            leaf = p.segments[-1]
            sel = None
            for s in leaf.selectors:
                if s.kind == SelectorKind.TESTID:
                    sel = f'[data-testid="{s.value}"]'
                    break
                if s.kind == SelectorKind.ID:
                    sel = f"#{s.value}"
                    break
            if sel is None:
                sel = leaf.tag
            if sel and sel not in seen:
                seen.add(sel)
                out.append(sel)
    return out


def _envelope_group_key(envelope: Dict[str, Any], fallback_name: str) -> str:
    """Group key for related envelopes in one HTML page.

    Visual plugin emits ``<scenario>.<urlkey>.tree`` and
    ``<scenario>.<urlkey>.screenshot`` per URL; both should render
    into one report. Strip the trailing ``.tree`` / ``.screenshot``
    suffix to find the shared prefix.
    """
    SUFFIXES = (".tree", ".screenshot")
    for suffix in SUFFIXES:
        if fallback_name.endswith(suffix):
            return fallback_name[: -len(suffix)]
    return fallback_name


def _envelope_test_result(envelope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pull the scenario.assertions observation out of an envelope, if
    present. Returns ``{passed, checked, violations}`` or None."""
    for obs in envelope.get("observations", []):
        if obs.get("id") == "scenario.assertions":
            return {
                "passed":  bool(obs.get("passed")),
                "checked": obs.get("checked_count", 0),
                "violations": obs.get("violations_count", 0),
            }
    return None


def _build_label_index_html(
    dim_name: str, label: str, rows: List[Dict[str, Any]],
) -> str:
    """Build the per-label index.html with prominent pass/fail badges."""
    from html import escape as _esc

    passed = sum(1 for r in rows if r["result"] and r["result"]["passed"])
    failed = sum(
        1 for r in rows if r["result"] and not r["result"]["passed"]
    )
    no_result = sum(1 for r in rows if r["result"] is None)
    total = len(rows)

    summary_chips = []
    if passed:
        summary_chips.append(
            f'<span class="chip pass">{passed}/{total} passed</span>'
        )
    if failed:
        summary_chips.append(
            f'<span class="chip fail">{failed} failed</span>'
        )
    if no_result:
        summary_chips.append(
            f'<span class="chip info">{no_result} other</span>'
        )

    rows_html: List[str] = []
    for r in rows:
        env = r["env_name"]
        result = r["result"]
        scenario = r["scenario"]
        if result is None:
            badge = '<span class="chip info">no test</span>'
            detail = ""
        elif result["passed"]:
            badge = '<span class="chip pass">✓ pass</span>'
            detail = (
                f'<span class="detail">{result["checked"]} checked</span>'
            )
        else:
            badge = '<span class="chip fail">✗ fail</span>'
            detail = (
                f'<span class="detail">'
                f'{result["violations"]} violation(s) · '
                f'{result["checked"]} checked</span>'
            )
        scen_html = (
            f'<span class="meta">scenario <code>{_esc(scenario)}</code></span>'
            if scenario else ""
        )
        rows_html.append(
            f'<li>{badge}<a href="{_esc(env)}.html">{_esc(env)}</a>'
            f' {scen_html} {detail}</li>'
        )

    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(dim_name)} / {_esc(label)}</title>"
        "<style>"
        "body{font:16px/1.5 system-ui,sans-serif;max-width:780px;"
        "margin:2rem auto;padding:1rem;color:#1f2937;}"
        "h1{margin:0 0 .5rem;}"
        ".summary{margin-bottom:1.2rem;}"
        ".chip{display:inline-block;padding:.1em .6em;border-radius:.4em;"
        "font-size:.85rem;font-weight:600;margin-right:.4em;color:#fff;}"
        ".chip.pass{background:#22c55e;}"
        ".chip.fail{background:#ef4444;}"
        ".chip.info{background:#3b82f6;}"
        "ul{list-style:none;padding:0;margin:0;}"
        "li{display:flex;align-items:center;gap:.5rem;padding:.6rem .8rem;"
        "margin:.4rem 0;border:1px solid #e5e7eb;border-radius:.5rem;"
        "background:#fff;flex-wrap:wrap;}"
        "li a{color:#2563eb;text-decoration:none;font-weight:600;}"
        "li a:hover{text-decoration:underline;}"
        ".meta{color:#6b7280;font-size:.9rem;}"
        ".detail{color:#6b7280;font-size:.85rem;margin-left:auto;}"
        "code{font:.9em/1.4 ui-monospace,Menlo,Consolas,monospace;}"
        "</style></head><body>"
        f"<h1>{_esc(dim_name)} / {_esc(label)}</h1>"
        f'<div class="summary">{" ".join(summary_chips)}</div>'
        f'<ul>{"".join(rows_html)}</ul>'
        "</body></html>"
    )


def _scenario_paths(roots) -> Dict[tuple, Path]:
    """Re-glob the discovery roots so we know where each scenario lives.

    Discovery returns parsed `Scenario` objects but not their on-disk
    paths; this small helper rebuilds the (plugin, name) → path index
    using the same `*.json` rglob so `provenance.path` can point at the
    source file.
    """
    out: Dict[tuple, Path] = {}
    for r in roots:
        rp = Path(r)
        if not rp.is_dir():
            continue
        for path in sorted(rp.rglob("*.json")):
            try:
                raw = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict):
                continue
            key = (raw.get("plugin"), raw.get("name"))
            if all(key):
                out.setdefault(key, path)
    return out


def cmd_capture_to_fixture(args: argparse.Namespace) -> int:
    """Extract a UIPath-keyed fixture JSON from a captured snapshot.

    Reads <dim>/<label>/<envelope>.snap.json, walks its `page.dom_tree`
    payload, derives a canonical UIPath for every node, and emits a
    fixture matching the compact UIPath-keyed `dom_walk` shape the
    framework's fixture loader accepts.

    `--trim` filters which nodes appear:
      * ``meaningful`` (default) — nodes with text, testid, role, name,
        or an interactive tag (a/button/input/select/textarea/label)
      * ``all`` — every node in the captured walk
      * ``text-only`` — nodes with non-empty direct text
    """
    import json as _json

    dims = _build_dims(Path(args.config))
    if not dims.exists(args.dim, args.label):
        print(f"error: snapshot {args.dim}/{args.label} not found",
              file=sys.stderr)
        return 1
    try:
        env = dims.load(args.dim, args.label, args.envelope)
    except SnapshotValidationError as e:
        print(f"✗ {args.dim}/{args.envelope}: {e}", file=sys.stderr)
        return 1

    dom_tree = next(
        (o for o in env.get("observations", [])
         if o.get("payload_schema") == "dom_tree"), None,
    )
    if dom_tree is None:
        print(f"error: envelope {args.envelope!r} has no dom_tree payload",
              file=sys.stderr)
        return 1

    walk = _flatten_dom_tree(dom_tree["data"].get("root"))
    from dimensions.uipath import derive_all, format_uipath
    paths = derive_all(walk)

    selected_keys = []
    selected_props = {}
    for node in walk:
        if not _node_is_interesting(node, args.trim):
            continue
        key = format_uipath(paths[node["idx"]])
        props = {}
        text = (node.get("text") or "").strip()
        if text:
            props["text"] = text
        selected_keys.append(key)
        selected_props[key] = props

    dom_walk_map = {k: selected_props[k] for k in selected_keys}

    subject = env.get("subject") or {}
    # The test framework drives a fixture protocol under the URL name
    # `main`, so an envelope captured as `home.tree` is replayed as
    # `main.tree`. Translate so the resulting fixture's expectations
    # match what the replay harness will actually produce.
    env_suffix = (
        args.envelope.split(".", 1)[-1] if "." in args.envelope
        else args.envelope
    )
    replayed_envelope = f"main.{env_suffix}"
    fixture = {
        "name": args.name or f"{args.label}_{args.envelope}",
        "plugin": args.dim,
        "protocol": "browser",
        "fixture": {
            "url": subject.get("url", ""),
            "title": next(
                (o.get("value") for o in env.get("observations", [])
                 if o.get("id") == "page.title"), "",
            ),
            "dom_walk": dom_walk_map,
        },
        "expectations": {
            "envelopes": [replayed_envelope],
            "observations_must_include": ["page.dom_tree", "page.screen_map"],
        },
    }

    out_path = Path(args.out) if args.out else Path(
        f"tests/scenarios/{args.dim}/{fixture['name']}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_json.dumps(fixture, indent=2) + "\n")
    _print(
        f"✓ wrote fixture with {len(dom_walk_map)} elements → {out_path}"
    )
    return 0


def _flatten_dom_tree(root, parent_idx=-1, out=None):
    """Recreate a flat dom_walk from a nested dom_tree payload."""
    if out is None:
        out = []
    if root is None:
        return out
    idx = len(out)
    view = {k: v for k, v in root.items() if k != "children"}
    view["idx"] = idx
    view["parent"] = parent_idx
    out.append(view)
    for child in root.get("children") or []:
        _flatten_dom_tree(child, idx, out)
    return out


def _node_is_interesting(node, mode: str) -> bool:
    if mode == "all":
        return True
    attrs = node.get("attributes") or {}
    text = (node.get("text") or "").strip()
    if mode == "text-only":
        return bool(text)
    # default: meaningful
    if text:
        return True
    if attrs.get("data-testid") or attrs.get("data-test-id"):
        return True
    if attrs.get("role") or node.get("role"):
        return True
    if attrs.get("name"):
        return True
    if (node.get("tag") or "").lower() in {
        "a", "button", "input", "select", "textarea", "label",
        "h1", "h2", "h3", "h4", "h5", "h6", "form",
    }:
        return True
    return False


def cmd_comment(args: argparse.Namespace) -> int:
    """Append a comment or resolution to a label's sidecar JSON."""
    from dimensions.comments import (
        Comment, Resolution, append_entry, load_comments,
        make_document_id, new_comment_id, now_utc,
    )

    dims = _build_dims(Path(args.config))
    backend = dims.backend
    targets = _targets(dims, args.dim)
    if not targets:
        print("error: no dimensions match", file=sys.stderr)
        return 1
    dim_name = targets[0]
    if not dims.exists(dim_name, args.label):
        print(f"error: snapshot {dim_name}/{args.label} not found",
              file=sys.stderr)
        return 1

    label_dir = backend._label_dir(dim_name, args.label)

    if args.comment_action == "list":
        for e in load_comments(label_dir):
            extra = f" [{e.resolution}]" if hasattr(e, "resolution") else ""
            target = e.parent_entity_id or "(report)"
            print(f"{e.date.isoformat()} {e.author} {e.type}{extra} → "
                  f"{e.parent_document_id} :: {target}\n  {e.text}")
        return 0

    parent_doc = make_document_id(dim_name, args.label, args.envelope)
    common = dict(
        id=new_comment_id(),
        parent_document_id=parent_doc,
        parent_entity_id=args.entity_id,
        date=now_utc(),
        author=args.author,
        text=args.text,
    )
    if args.comment_action == "resolve":
        entry = Resolution(**common, resolution=args.resolution)
    else:
        entry = Comment(**common)
    path = append_entry(label_dir, entry)
    _print(f"✓ {args.comment_action} → {path}")
    return 0


_DISPATCH = {
    "list": cmd_list,
    "list-snapshots": cmd_list_snapshots,
    "schema": cmd_schema,
    "inspect": cmd_inspect,
    "capture": cmd_capture,
    "show": cmd_show,
    "report": cmd_report,
    "diff": cmd_diff,
    "render-html": cmd_render_html,
    "render-md": cmd_render_md,
    "render-diff": cmd_render_diff,
    "comment": cmd_comment,
    "capture-to-fixture": cmd_capture_to_fixture,
    "scenarios": cmd_scenarios,
}


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    scope, remaining = _extract_scope_token(argv)

    parser = build_parser()
    args = parser.parse_args(remaining)
    # `all` means "every applicable dimension" — handlers expect None for that.
    args.dim = None if scope in (None, _ALL_SCOPE) else scope  # type: ignore[attr-defined]

    handler = _DISPATCH[args.cmd]
    try:
        return handler(args)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except SnapshotValidationError as e:
        print(f"Validation error:\n{e}", file=sys.stderr)
        return 1
