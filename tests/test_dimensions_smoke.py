"""End-to-end smoke test for the dimensions framework.

Exercises every supported report visualization for every supported dimension
and writes real reports to ``dimensions-reports/`` so the test doubles as
the canonical example of how the framework's outputs are produced.

Supported visualizations covered:
  - render_envelope_markdown    → per-snapshot, per-dim
  - render_comparison_markdown  → per-dim diff with decisions placeholder

Supported dimensions covered:
  - data    (uses prep/superset.k.json)
  - visual  (uses a temp HTTP server on :8501; if Playwright/system libs are
             missing, the plugin emits a degraded envelope — the test still
             passes because that path is part of the contract)

Run with:
    python3 -m pytest tests/test_dimensions_smoke.py -v
"""

from __future__ import annotations

import http.server
import socketserver
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterator, Tuple

import pytest

from dimensions import Dimensions
from dimensions.config import Config
from dimensions.render import (
    render_comparison_markdown,
    render_envelope_markdown,
)
from dimensions.validate import SnapshotValidationError, validate_envelope


WORKSPACE = Path(__file__).resolve().parent.parent
CONFIG_PATH = WORKSPACE / "dimensions.config.yaml"
REPORTS_DIR = WORKSPACE / "dimensions-reports"

PAGE_V1 = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Smoke v1</title></head>
<body>
  <h1>Smoke test page</h1>
  <h2>Section A</h2>
  <p>Hello.</p>
  <ul><li>one</li><li>two</li></ul>
  <img src="a.png" alt="ok"/>
</body></html>
"""

PAGE_V2 = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Smoke v2</title></head>
<body>
  <h1>Smoke test page</h1>
  <h2>Section A</h2>
  <h3>Section A.1 (added)</h3>
  <p>Hello.</p>
  <p>Extra paragraph.</p>
  <ul><li>one</li><li>two</li><li>three</li></ul>
  <img src="a.png" alt="ok"/>
</body></html>
"""


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def page_dir() -> Iterator[Path]:
    """Temp dir whose ``index.html`` we mutate between snapshots."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "index.html").write_text(PAGE_V1)
        yield d


@pytest.fixture
def static_server(page_dir: Path) -> Iterator[Tuple[Path, "socketserver.TCPServer", int]]:
    """Tiny HTTP server bound to a free localhost port."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(page_dir), **kw)

        def log_message(self, *_):  # silence
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    try:
        yield page_dir, srv, port
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def runner(tmp_path: Path, monkeypatch, static_server) -> Dimensions:
    """A Dimensions registry wired to a fresh per-test snapshots backend.

    Plugins resolve paths against cwd, so we chdir into the workspace so
    relative source paths in ``dimensions.config.yaml`` resolve. The
    backend is rerouted to ``tmp_path`` and the visual plugin is pointed
    at the test's own static server (whose port we just allocated).
    """
    _page_dir, _srv, port = static_server
    monkeypatch.chdir(WORKSPACE)
    cfg = Config.from_file(CONFIG_PATH)
    cfg.backend = {"type": "filesystem", "path": str(tmp_path / "snapshots")}
    for entry in cfg.plugins:
        if entry.get("module") == "plugins.visual":
            entry.setdefault("config", {})["urls"] = [
                {"name": "home", "url": f"http://127.0.0.1:{port}/"}
            ]
    return Dimensions(cfg)


# ── the test ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_smoke_generates_reports_for_every_supported_dimension(
    runner: Dimensions,
    static_server: Tuple[Path, "socketserver.TCPServer", int],
) -> None:
    """Capture two labels, render every envelope, persist diff to disk.

    Asserts:
      1. Capture succeeds for every applicable dimension (data + visual).
      2. Each captured envelope is Pydantic-valid (`Dimensions.capture`
         already validates; a re-load + re-validate confirms persistence).
      3. Per-dimension snapshot reports are written and non-empty.
      4. The diff report contains an envelope-keyed comparison and a
         ``Decisions`` block per envelope.
      5. The visual diff (after the page mutation) reports actual changes.
    """
    page_dir, _srv, _port = static_server

    if REPORTS_DIR.exists():
        for p in REPORTS_DIR.rglob("*"):
            if p.is_file():
                p.unlink()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── capture baseline ────────────────────────────────────────────────
    baseline = await runner.capture("baseline")
    assert set(baseline.keys()) <= {"data", "visual"}, (
        f"unexpected dim names: {list(baseline.keys())}"
    )

    # ── mutate the page so visual has a non-trivial diff ───────────────
    (page_dir / "index.html").write_text(PAGE_V2)

    current = await runner.capture("current")
    assert set(current.keys()) == set(baseline.keys())

    # ── per-(dim, envelope) snapshot reports ───────────────────────────
    for dim in runner.list_known():
        if dim not in baseline:
            continue   # not applicable in this run (e.g. visual without server)
        out_dir = REPORTS_DIR / dim
        out_dir.mkdir(parents=True, exist_ok=True)
        for label in ("baseline", "current"):
            # Asset loader so screenshot payloads embed inline as base64
            # (the markdown reports live outside the snapshot tree, so a
            # relative `assets/<hash>` path wouldn't resolve).
            loader = lambda sha, _d=dim, _l=label: runner.read_asset(_d, _l, sha)
            for env_name in runner.list_envelopes(dim, label):
                envelope = runner.load(dim, label, env_name)
                validate_envelope(envelope)
                out_path = out_dir / f"{label}.{env_name}.md"
                out_path.write_text(
                    render_envelope_markdown(envelope, asset_loader=loader)
                )
                text = out_path.read_text()
                assert text.startswith("## Dimension:"), (
                    f"envelope render missing markdown header in {out_path}"
                )

    # ── diff report ────────────────────────────────────────────────────
    comparison = runner.compare("baseline", "current")
    diff_md_parts = ["# Comparison: `baseline` → `current`\n"]
    decisions_block_count = 0
    for dim, dim_report in comparison.items():
        for env_name, result in dim_report.get("envelopes", {}).items():
            assert "error" not in result, (
                f"dim {dim}/{env_name} compare errored: {result}"
            )
            assert result["decisions"] == {}
            diff_md_parts.append(
                render_comparison_markdown(
                    f"{dim}/{env_name}",
                    result["changes"],
                    decisions=result["decisions"],
                )
            )
            decisions_block_count += 1

    diff_path = REPORTS_DIR / "diff_baseline_vs_current.md"
    diff_path.write_text("\n".join(diff_md_parts))
    diff_text = diff_path.read_text()
    assert decisions_block_count >= 1, "expected at least one envelope diff"
    assert diff_text.count("### Decisions") == decisions_block_count
    assert "snapshots themselves stay immutable" in diff_text

    # The visual dim, when applicable, should show real changes (page was
    # mutated between captures). The data dim should show no changes.
    if "visual" in comparison:
        visual_changes_total = sum(
            len(r.get("changes") or {})
            for r in comparison["visual"].get("envelopes", {}).values()
        )
        assert visual_changes_total >= 1, "page mutation should yield diffs"
    if "data" in comparison:
        for env_name, r in comparison["data"].get("envelopes", {}).items():
            assert r.get("changes") == {}, (
                f"data/{env_name} unchanged between captures but diff says: {r}"
            )

    # ── every persisted envelope validates against the schema ───────────
    snapshots_root = runner.backend.base_dir
    validated = 0
    for snap_path in snapshots_root.rglob("*.snap.json"):
        envelope_dict = __import__("json").loads(snap_path.read_text())
        try:
            validate_envelope(envelope_dict)
        except SnapshotValidationError as e:
            pytest.fail(f"persisted envelope failed validation: {snap_path}\n{e}")
        validated += 1
    assert validated >= 2, (
        f"expected at least 2 envelopes persisted, got {validated}"
    )

    # ── summary written so a developer can find the reports ────────────
    print()
    print("Reports written to:", REPORTS_DIR)
    for p in sorted(REPORTS_DIR.rglob("*.md")):
        print(f"  {p.relative_to(WORKSPACE)}")
