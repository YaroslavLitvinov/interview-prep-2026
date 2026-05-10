"""File-source injection protocol for the Data dimension.

`JsonFileProtocol` reads JSON files (async-friendly via `asyncio.to_thread`)
and provides a default JSON-aware comparator so envelopes carrying parsed
JSON payloads diff structurally even when the framework's diff engine
only sees opaque dicts.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

from dimensions.injection import BaseInjectionProtocol


class JsonFileProtocol(BaseInjectionProtocol):
    """Concrete file-source protocol — reads JSON, compares structurally."""

    name = "json_file"

    async def read_text(self, path: Path) -> str:
        return await asyncio.to_thread(Path(path).read_text)

    async def read_bytes(self, path: Path) -> bytes:
        return await asyncio.to_thread(Path(path).read_bytes)

    async def read_json(self, path: Path) -> Any:
        text = await self.read_text(path)
        return json.loads(text)

    async def exists(self, path: Path) -> bool:
        return await asyncio.to_thread(Path(path).exists)

    # ── comparator override ──────────────────────────────────────────────

    def compare(
        self,
        before: Any,
        after: Any,
        envelope_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if before == after:
            return None
        return _json_diff(before, after, path="$")


def _json_diff(a: Any, b: Any, *, path: str) -> Dict[str, Any]:
    """Path-keyed structural diff for JSON values."""
    if type(a) is not type(b):
        return {"changed": [{"path": path, "before": a, "after": b}]}
    if isinstance(a, dict):
        changes = []
        for k in sorted(set(a) | set(b)):
            sub_path = f"{path}.{k}"
            if k not in a:
                changes.append({"path": sub_path, "added": b[k]})
            elif k not in b:
                changes.append({"path": sub_path, "removed": a[k]})
            elif a[k] != b[k]:
                inner = _json_diff(a[k], b[k], path=sub_path)
                changes.extend(inner.get("changed", []))
        return {"changed": changes}
    if isinstance(a, list):
        if len(a) != len(b):
            return {"changed": [{"path": path, "len_before": len(a), "len_after": len(b)}]}
        changes = []
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                inner = _json_diff(x, y, path=f"{path}[{i}]")
                changes.extend(inner.get("changed", []))
        return {"changed": changes}
    return {"changed": [{"path": path, "before": a, "after": b}]}
