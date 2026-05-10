"""Filesystem-backed snapshot store.

Layout::

    <base_dir>/<dimension>/<label>/<envelope_name>.snap.json
    <base_dir>/<dimension>/<label>/assets/<sha256><ext>

`.snap.json` extension marks operational snapshot files (distinct from
project knowledge documents under `.k.json`). Assets are content-addressed
PNG / HTML / etc. blobs referenced from `payload` observations.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from dimensions.store.base import SnapshotBackend


class FilesystemBackend(SnapshotBackend):
    """Stores envelopes + assets as files on disk."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    # ── path helpers ─────────────────────────────────────────────────────

    def _label_dir(self, dimension_name: str, label: str) -> Path:
        return self.base_dir / dimension_name / label

    def _envelope_path(
        self, dimension_name: str, label: str, envelope_name: str
    ) -> Path:
        return self._label_dir(dimension_name, label) / f"{envelope_name}.snap.json"

    def _assets_dir(self, dimension_name: str, label: str) -> Path:
        return self._label_dir(dimension_name, label) / "assets"

    # ── envelopes ─────────────────────────────────────────────────────────

    def save(
        self,
        dimension_name: str,
        label: str,
        envelope_name: str,
        envelope: Dict[str, Any],
    ) -> str:
        path = self._envelope_path(dimension_name, label, envelope_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(envelope, indent=2, default=str, sort_keys=True)
        )
        tmp.replace(path)
        return str(path)

    def load(
        self, dimension_name: str, label: str, envelope_name: str
    ) -> Dict[str, Any]:
        return json.loads(
            self._envelope_path(dimension_name, label, envelope_name).read_text()
        )

    def envelope_exists(
        self, dimension_name: str, label: str, envelope_name: str
    ) -> bool:
        return self._envelope_path(dimension_name, label, envelope_name).exists()

    def label_exists(self, dimension_name: str, label: str) -> bool:
        d = self._label_dir(dimension_name, label)
        if not d.is_dir():
            return False
        return any(c.name.endswith(".snap.json") for c in d.iterdir())

    # ── inventory ─────────────────────────────────────────────────────────

    def list_labels(self, dimension_name: str) -> List[str]:
        dim_dir = self.base_dir / dimension_name
        if not dim_dir.is_dir():
            return []
        return sorted(
            p.name for p in dim_dir.iterdir()
            if p.is_dir() and any(c.name.endswith(".snap.json") for c in p.iterdir())
        )

    def list_envelopes(self, dimension_name: str, label: str) -> List[str]:
        d = self._label_dir(dimension_name, label)
        if not d.is_dir():
            return []
        return sorted(
            p.name[: -len(".snap.json")]
            for p in d.iterdir()
            if p.name.endswith(".snap.json")
        )

    def list_dimensions(self) -> List[str]:
        if not self.base_dir.is_dir():
            return []
        return sorted(
            p.name for p in self.base_dir.iterdir()
            if p.is_dir() and any(c.is_dir() for c in p.iterdir())
        )

    # ── assets ────────────────────────────────────────────────────────────

    def save_asset(
        self,
        dimension_name: str,
        label: str,
        sha256: str,
        ext: str,
        content: bytes,
    ) -> str:
        assets = self._assets_dir(dimension_name, label)
        assets.mkdir(parents=True, exist_ok=True)
        path = assets / f"{sha256}{ext}"
        if path.exists():
            return str(path)  # content-addressed → already stored, dedup
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(content)
        tmp.replace(path)
        return str(path)

    def read_asset(
        self, dimension_name: str, label: str, sha256: str
    ) -> bytes:
        assets = self._assets_dir(dimension_name, label)
        for p in assets.iterdir():
            if p.name.startswith(sha256):
                return p.read_bytes()
        raise FileNotFoundError(
            f"asset {sha256} not found under {assets}"
        )
