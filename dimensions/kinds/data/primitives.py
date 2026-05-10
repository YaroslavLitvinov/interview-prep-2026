"""Framework primitives for the Data dimension.

Plugins delegate JSON inspection to these functions. The plugin only
configures which file to inspect; the primitives push observations onto
the EnvelopeBuilder the plugin opened with `ctx.envelope(...)`.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from dimensions.api import EnvelopeBuilder


def hash_file(path: Path) -> str:
    """Compute SHA-256 of a file. Returns empty string if missing."""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def file_subject_dict(path: Path) -> Dict[str, Any]:
    """Build a FileSubject dict for `ctx.envelope(subject=...)`."""
    path = Path(path)
    subject: Dict[str, Any] = {"kind": "file", "path": str(path)}
    if path.exists():
        subject["sha256"] = hash_file(path)
        subject["size_bytes"] = file_size(path)
    return subject


def walk_json(env: "EnvelopeBuilder", path: Path) -> None:
    """Walk a JSON file and push observations onto `env`.

    The plugin remains thin — it only opens the envelope (with subject)
    and calls this primitive. All Data-dimension observation IDs are
    emitted by this function, keeping the convention in the framework.
    """
    path = Path(path)

    if not path.exists():
        env.boolean("file.exists", "Source file exists", False)
        return

    env.boolean("file.exists", "Source file exists", True)
    env.scalar("file.size_bytes", "File size", file_size(path), unit="bytes")

    try:
        with open(path) as f:
            data = json.load(f)
        env.boolean("file.json_valid", "File parses as JSON", True)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        env.boolean("file.json_valid", "File parses as JSON", False)
        env.rule_check(
            "file.json_parse",
            "File can be parsed as JSON",
            passed=False,
            violations=[{"error": str(e)[:200]}],
            checked_count=1,
        )
        return

    env.rule_check(
        "file.json_parse",
        "File can be parsed as JSON",
        passed=True,
        checked_count=1,
    )

    type_counter: Counter = Counter()
    key_counter: Counter = Counter()
    leaf_counter = [0]
    max_depth = [0]

    def walk(node: Any, depth: int = 0) -> None:
        if depth > max_depth[0]:
            max_depth[0] = depth
        type_counter[type(node).__name__] += 1
        if isinstance(node, dict):
            for k, v in node.items():
                key_counter[k] += 1
                walk(v, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
        else:
            leaf_counter[0] += 1

    walk(data)

    env.scalar("structure.max_depth", "Maximum hierarchy depth", max_depth[0])
    env.scalar("structure.leaf_count", "Total leaf values", leaf_counter[0])
    env.scalar(
        "structure.node_count",
        "Total nodes (incl. containers)",
        sum(type_counter.values()),
    )
    env.distribution(
        "structure.value_types",
        "Value type distribution",
        {k: int(v) for k, v in type_counter.items()},
    )
    env.histogram(
        "structure.keys",
        "Key frequency",
        {k: int(v) for k, v in key_counter.items()},
        top_n=30,
    )
    env.set(
        "structure.unique_keys",
        "Distinct keys observed anywhere in the document",
        list(key_counter.keys()),
    )

    if isinstance(data, dict):
        env.set(
            "structure.top_level_keys",
            "Keys at the document root",
            sorted(data.keys()),
        )
