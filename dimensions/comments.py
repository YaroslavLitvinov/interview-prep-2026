"""Comments and resolutions sidecar for snapshots.

Comments live next to a snapshot label as ``comments.json``:

    <base_dir>/<dimension>/<label>/comments.json

The file is a flat list of entries (Comment | Resolution). Both anchor
to a ``parent_entity_id`` — the content-derived stable id stamped onto
observations by the framework — so they survive recapture. A
``parent_entity_id`` of ``None`` means the comment is on the report
itself (envelope-level), keyed by ``parent_document_id``
(``<dimension>/<label>/<envelope_name>``).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class Comment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["comment"] = "comment"
    id: str = Field(..., description="Unique id for the comment itself.")
    parent_document_id: str = Field(
        ...,
        description="`<dimension>/<label>/<envelope_name>` — the report.",
    )
    parent_entity_id: Optional[str] = Field(
        default=None,
        description=(
            "Content-derived id of the observation being commented on. "
            "None means the comment targets the whole report."
        ),
    )
    date: datetime
    author: str
    text: str


class Resolution(Comment):
    """A comment that also records an approval decision."""

    type: Literal["resolution"] = "resolution"
    resolution: Literal["approved", "denied"]


CommentEntry = Union[Resolution, Comment]
_AdapterList = TypeAdapter(List[CommentEntry])


def comments_path(label_dir: Path) -> Path:
    return Path(label_dir) / "comments.json"


def load_comments(label_dir: Path) -> List[CommentEntry]:
    p = comments_path(label_dir)
    if not p.exists():
        return []
    raw = json.loads(p.read_text() or "[]")
    return _AdapterList.validate_python(raw)


def save_comments(label_dir: Path, entries: List[CommentEntry]) -> Path:
    p = comments_path(label_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = _AdapterList.dump_python(entries, mode="json")
    p.write_text(json.dumps(payload, indent=2, default=str))
    return p


def append_entry(label_dir: Path, entry: CommentEntry) -> Path:
    entries = load_comments(label_dir)
    entries.append(entry)
    return save_comments(label_dir, entries)


def make_document_id(dimension: str, label: str, envelope_name: str) -> str:
    return f"{dimension}/{label}/{envelope_name}"


def new_comment_id() -> str:
    """Short random id sufficient for an append-only log."""
    import secrets
    return "c_" + secrets.token_hex(6)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
