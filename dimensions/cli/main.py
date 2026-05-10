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
from typing import Any, Dict, List, Optional

from dimensions.config import DEFAULT_CONFIG_NAME
from dimensions.dimensions import Dimensions
from dimensions.kinds import KIND_REGISTRY
from dimensions.render import (
    render_comparison_markdown,
    render_envelope_markdown,
)
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
    dims = _build_dims(Path(args.config))
    captured = asyncio.run(
        dims.capture(args.label, dimension_name=args.dim)
    )
    if not captured:
        _print("No applicable dimensions to capture.")
        return 1
    _print(f"Captured snapshot `{args.label}`:")
    for dim_name, result in captured.items():
        for env in result.envelopes:
            n_obs = len(env.get("observations", []))
            _print(
                f"  - {dim_name}/{env['envelope_name']}: "
                f"{n_obs} observations validated and stored"
            )
        if result.pending_assets:
            _print(
                f"    + {len(result.pending_assets)} asset(s) → "
                f".dimensions/snapshots/{dim_name}/{args.label}/assets/"
            )
    return 0


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
        _print(f"_No envelopes for label `{args.label}`._")
        return 1
    _print(f"✓ wrote {written} markdown file(s) → {Path(args.out)}")
    return 0


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
        index_links: List[str] = []
        for env_name in env_names:
            try:
                envelope = dims.load(name, args.label, env_name)
            except SnapshotValidationError as e:
                print(f"✗ {name}/{env_name}: {e}", file=sys.stderr)
                continue
            ir = schema.render_envelope(envelope)
            html = HtmlRenderer(
                asset_loader=loader,
                inline_assets=args.inline_assets,
                title=f"{name} / {args.label} / {env_name}",
            ).render(ir)
            (out_dir / f"{env_name}.html").write_text(html)
            index_links.append(f'<li><a href="{env_name}.html">{env_name}</a></li>')
            written += 1

        if index_links:
            (out_dir / "index.html").write_text(
                f"<!doctype html><html lang=en><head><meta charset=utf-8>"
                f"<meta name=viewport content='width=device-width,initial-scale=1'>"
                f"<title>{name} / {args.label}</title>"
                f"<style>body{{font:16px/1.5 sans-serif;max-width:600px;margin:2rem auto;padding:1rem}}"
                f"a{{color:#2563eb;text-decoration:none}}</style></head><body>"
                f"<h1>{name} / {args.label}</h1><ul>{''.join(index_links)}</ul>"
                f"</body></html>"
            )

    if not written:
        _print(f"_No envelopes for label `{args.label}`._")
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

    return parser


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
