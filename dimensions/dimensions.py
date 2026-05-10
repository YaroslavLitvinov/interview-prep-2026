"""Dimensions — the single user-facing entry point.

    dims = Dimensions("dimensions.config.yaml")
    await dims.collect()         # async — plugins drive Playwright etc.

Or programmatically:

    dims = Dimensions()
    dims.add(Dimension(DataPlugin(sources=[...])))
    await dims.collect()

Plugins evaluate their own paths; the framework does not impose a project
root. Snapshots default to ``./.dimensions`` (or whatever the config
declares); pass a `Config` if you need a different layout.

Storage layout (filesystem backend):

    .dimensions/snapshots/<dim>/<label>/<envelope_name>.snap.json
    .dimensions/snapshots/<dim>/<label>/assets/<sha256><ext>
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dimensions.diff import diff_envelopes
from dimensions.dimension import CollectionResult, Dimension
from dimensions.validate import (
    SnapshotValidationError,
    validate_envelope,
)


ConfigInput = Union[str, Path, "Config"]  # noqa: F821 — forward reference


class Dimensions:
    """Project-level container and orchestrator for a set of `Dimension`s."""

    DEFAULT_SNAPSHOTS_DIR = ".dimensions"

    def __init__(self, config: Optional[ConfigInput] = None) -> None:
        from dimensions.config import Config
        from dimensions.store.filesystem import FilesystemBackend

        cfg: Optional[Config]
        if isinstance(config, (str, Path)):
            cfg = Config.from_file(Path(config))
        elif isinstance(config, Config):
            cfg = config
        elif config is None:
            cfg = None
        else:
            raise TypeError(
                f"config must be a str, Path, or Config; got {type(config).__name__}"
            )

        if cfg is not None:
            self.backend = cfg.build_backend(Path.cwd())
            self.schemas: Dict[str, Any] = dict(cfg.schemas)
        else:
            self.backend = FilesystemBackend(Path.cwd() / self.DEFAULT_SNAPSHOTS_DIR)
            self.schemas = {}

        self._dimensions: List[Dimension] = []
        if cfg is not None:
            for dimension in cfg.load_dimensions(schemas=self.schemas):
                self.add(dimension)

    # ── registration ──────────────────────────────────────────────────────

    def add(self, dimension: Dimension) -> None:
        if not isinstance(dimension, Dimension):
            raise TypeError(
                f"Dimensions.add expects a Dimension instance, got "
                f"{type(dimension).__name__}"
            )
        self._dimensions.append(dimension)

    def applicable(self) -> List[Dimension]:
        return [d for d in self._dimensions if d.is_applicable()]

    # ── lifecycle ────────────────────────────────────────────────────────

    async def collect(
        self, dimension_name: Optional[str] = None
    ) -> Dict[str, CollectionResult]:
        """Run every applicable dimension's collect concurrently."""
        targets = [
            d for d in self.applicable()
            if dimension_name is None or d.name == dimension_name
        ]
        results = await asyncio.gather(*(d.collect() for d in targets))
        return {d.name: r for d, r in zip(targets, results)}

    async def capture(
        self, label: str, dimension_name: Optional[str] = None
    ) -> Dict[str, CollectionResult]:
        """Collect + persist (envelopes and assets) for every applicable dimension."""
        results = await self.collect(dimension_name=dimension_name)
        for name, result in results.items():
            for envelope in result.envelopes:
                self.backend.save(
                    name, label, envelope["envelope_name"], envelope
                )
            for sha, (content, ext, mime_type) in result.pending_assets.items():
                self.backend.save_asset(name, label, sha, ext, content)
        return results

    inspect = collect  # naming alias

    def load(
        self, dimension_name: str, label: str, envelope_name: str
    ) -> Dict[str, Any]:
        return validate_envelope(
            self.backend.load(dimension_name, label, envelope_name)
        )

    def load_all(self, dimension_name: str, label: str) -> List[Dict[str, Any]]:
        """Load every envelope under (dim, label)."""
        return [
            validate_envelope(self.backend.load(dimension_name, label, n))
            for n in self.backend.list_envelopes(dimension_name, label)
        ]

    def compare(
        self, baseline_label: str, current_label: str
    ) -> Dict[str, Dict[str, Any]]:
        """Compare every envelope under each applicable dimension's two labels."""
        report: Dict[str, Dict[str, Any]] = {}
        for d in self.applicable():
            baseline_names = set(self.backend.list_envelopes(d.name, baseline_label))
            current_names = set(self.backend.list_envelopes(d.name, current_label))
            shared = sorted(baseline_names & current_names)
            added = sorted(current_names - baseline_names)
            removed = sorted(baseline_names - current_names)
            per_envelope: Dict[str, Dict[str, Any]] = {}
            for name in shared:
                try:
                    baseline = self.load(d.name, baseline_label, name)
                    current = self.load(d.name, current_label, name)
                except SnapshotValidationError as e:
                    per_envelope[name] = {"error": str(e)}
                    continue
                per_envelope[name] = {
                    "changes": diff_envelopes(baseline, current),
                    "decisions": {},
                }
            report[d.name] = {
                "envelopes": per_envelope,
                "added_envelopes": added,
                "removed_envelopes": removed,
            }
        return report

    # ── inventory ────────────────────────────────────────────────────────

    def list_labels(self, dimension_name: str) -> List[str]:
        return self.backend.list_labels(dimension_name)

    def list_envelopes(self, dimension_name: str, label: str) -> List[str]:
        return self.backend.list_envelopes(dimension_name, label)

    def list_known(self) -> List[str]:
        return [d.name for d in self._dimensions]

    def exists(self, dimension_name: str, label: str) -> bool:
        return self.backend.label_exists(dimension_name, label)

    def read_asset(self, dimension_name: str, label: str, sha256: str) -> bytes:
        return self.backend.read_asset(dimension_name, label, sha256)
