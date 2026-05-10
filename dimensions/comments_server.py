"""Comments service — Phase B of the comments feature.

A small standalone HTTP server that:

  1. Statically serves the rendered ``dimensions-reports/`` tree so users
     open ``http://localhost:<port>/<dim>/<label>/<env>.html`` (or the
     ``…/baseline.vs.current/<env>.diff.html`` page) in a browser.

  2. Exposes a JSON API for reading and posting comments / resolutions
     into the same ``comments.json`` sidecar files the CLI writes:

       GET  /api/comments?dim=<dim>&label=<label>
            → list of entries for that snapshot label.

       POST /api/comments
            body: {dim, label, envelope_name, parent_entity_id?,
                    author, text}
            → appends a Comment, returns the saved entry.

       POST /api/resolutions
            body: {…, resolution: "approved"|"denied"}
            → appends a Resolution, returns the saved entry.

  3. For diff pages, comments are merged from BOTH labels client-side;
     posting from a diff page must specify which label the comment
     attaches to (the JS sends ``label`` explicitly).

The HTML reports remain self-contained: when opened over file:// they
fall back to the embedded JSON island. When opened from this server,
the embedded snapshot is replaced by a live fetch and a "post comment"
form appears on every observation card.

Run with::

    python -m dimensions.comments_server \\
        --reports-dir dimensions-reports \\
        --snapshots-dir .dimensions/snapshots \\
        --port 8765

``--reports-dir`` is the rendered HTML tree (what the user browses).
``--snapshots-dir`` is where the ``comments.json`` sidecars live —
typically the snapshot store base directory configured in
``dimensions.config.yaml``. Both default to common values.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from dimensions.comments import (
    Comment, Resolution, append_entry, load_comments,
    make_document_id, new_comment_id, now_utc,
)


def _require_fastapi() -> None:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as e:
        print(
            "error: this server needs fastapi + uvicorn installed.\n"
            "  pip install fastapi uvicorn\n"
            f"  (import failed: {e})",
            file=sys.stderr,
        )
        raise SystemExit(2)


# ── request models (loose; framework models are stricter) ─────────────────


class CommentIn(BaseModel):
    dim: str
    label: str
    envelope_name: str = "main"
    parent_entity_id: Optional[str] = None
    author: str = "anonymous"
    text: str = Field(..., min_length=1)


class ResolutionIn(CommentIn):
    resolution: Literal["approved", "denied"]


# ── server factory ────────────────────────────────────────────────────────


def build_app(reports_dir: Path, snapshots_dir: Path):
    _require_fastapi()
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    reports_dir = Path(reports_dir).resolve()
    snapshots_dir = Path(snapshots_dir).resolve()

    if not reports_dir.is_dir():
        print(
            f"warning: reports dir {reports_dir} does not exist yet — "
            "static routes will 404 until you run render-html / render-diff.",
            file=sys.stderr,
        )
    if not snapshots_dir.is_dir():
        print(
            f"warning: snapshots dir {snapshots_dir} does not exist yet — "
            "comment writes will create it on first POST.",
            file=sys.stderr,
        )

    app = FastAPI(title="dimensions comments service")

    # Same-origin in normal use; allow * so the user can also open the
    # rendered HTML directly from disk and still hit the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def _label_dir(dim: str, label: str) -> Path:
        # Mirror FilesystemBackend's layout: <snapshots>/<dim>/<label>/
        target = (snapshots_dir / dim / label).resolve()
        # Reject path-escape attempts. `is_relative_to` (3.9+) is exact.
        if not target.is_relative_to(snapshots_dir):
            raise HTTPException(400, "invalid dim/label")
        return target

    @app.get("/api/comments")
    def get_comments(
        dim: str = Query(...), label: str = Query(...),
    ) -> List[dict]:
        try:
            entries = load_comments(_label_dir(dim, label))
        except FileNotFoundError:
            return []
        return [e.model_dump(mode="json") for e in entries]

    @app.post("/api/comments")
    def post_comment(payload: CommentIn) -> dict:
        entry = Comment(
            id=new_comment_id(),
            parent_document_id=make_document_id(
                payload.dim, payload.label, payload.envelope_name,
            ),
            parent_entity_id=payload.parent_entity_id,
            date=now_utc(),
            author=payload.author,
            text=payload.text,
        )
        append_entry(_label_dir(payload.dim, payload.label), entry)
        return entry.model_dump(mode="json")

    @app.post("/api/resolutions")
    def post_resolution(payload: ResolutionIn) -> dict:
        entry = Resolution(
            id=new_comment_id(),
            parent_document_id=make_document_id(
                payload.dim, payload.label, payload.envelope_name,
            ),
            parent_entity_id=payload.parent_entity_id,
            date=now_utc(),
            author=payload.author,
            text=payload.text,
            resolution=payload.resolution,
        )
        append_entry(_label_dir(payload.dim, payload.label), entry)
        return entry.model_dump(mode="json")

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "reports_dir":   str(reports_dir),
            "snapshots_dir": str(snapshots_dir),
        }

    # Mount the rendered HTML tree last so /api routes win on conflict.
    if reports_dir.is_dir():
        app.mount(
            "/", StaticFiles(directory=str(reports_dir), html=True),
            name="reports",
        )

    return app


# ── CLI ───────────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m dimensions.comments_server",
        description="Serve dimensions reports + comments API.",
    )
    p.add_argument(
        "--reports-dir", default="dimensions-reports",
        help="Rendered HTML tree to serve (default: %(default)s).",
    )
    p.add_argument(
        "--snapshots-dir", default=".dimensions/snapshots",
        help="Snapshot base dir holding comments.json sidecars "
             "(default: %(default)s). Should match your snapshot backend.",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args(argv)

    _require_fastapi()
    import uvicorn
    app = build_app(Path(args.reports_dir), Path(args.snapshots_dir))
    print(
        f"→ serving {args.reports_dir!r} + comments API "
        f"at http://{args.host}:{args.port}/",
        file=sys.stderr,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
