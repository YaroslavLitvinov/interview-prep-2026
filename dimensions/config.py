"""Project configuration loader for `dimensions.config.yaml`.

The config is the only project-side coupling to the framework. It
declares the schema directory (auto-discovered registry), the plugins to
register, and the storage backend.

Example:

    schemas_dir: schemas/                # every <name>.spec.json registered as <name>

    plugins:
      - name: data
        module: plugins.data
        class: DataPlugin
        config:
          sources:
            - {name: superset, path: prep/superset.k.json, spec: superset}

      - name: visual
        module: plugins.visual
        class: VisualPlugin
        config:
          urls:
            - {name: home, url: http://localhost:8501/}
          viewport: { width: 1280, height: 720 }

    backend:
      type: filesystem
      path: .dimensions/snapshots

    reports_dir: dimensions-reports/
"""

from __future__ import annotations

import importlib
import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from dimensions.api import Plugin
from dimensions.dimension import Dimension
from dimensions.store.base import SnapshotBackend
from dimensions.store.filesystem import FilesystemBackend


DEFAULT_CONFIG_NAME = "dimensions.config.yaml"


@dataclass
class Config:
    plugins: List[Dict[str, Any]] = field(default_factory=list)
    backend: Dict[str, Any] = field(
        default_factory=lambda: {
            "type": "filesystem",
            "path": ".dimensions/snapshots",
        }
    )
    schemas_dir: Optional[str] = None
    schemas: Dict[str, Any] = field(default_factory=dict)
    reports_dir: str = "dimensions-reports/"

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {path}\n"
                f"Create one (see {DEFAULT_CONFIG_NAME} examples in dimensions/README.md)."
            )
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        cfg = cls(
            plugins=data.get("plugins", []),
            backend=data.get(
                "backend",
                {"type": "filesystem", "path": ".dimensions/snapshots"},
            ),
            schemas_dir=data.get("schemas_dir"),
            reports_dir=data.get("reports_dir", "dimensions-reports/"),
        )
        # Auto-discover specs in schemas_dir.
        if cfg.schemas_dir:
            base = Path(cfg.schemas_dir)
            if not base.is_absolute():
                base = path.resolve().parent / base
            cfg.schemas = _discover_schemas(base)
        return cfg

    def build_backend(self, base_dir: Optional[Path] = None) -> SnapshotBackend:
        kind = self.backend.get("type", "filesystem")
        if kind == "filesystem":
            base = Path(self.backend.get("path", ".dimensions/snapshots"))
            if not base.is_absolute():
                base = (Path(base_dir) if base_dir else Path.cwd()) / base
            return FilesystemBackend(base)
        raise ValueError(
            f"Unknown backend type: {kind}. Supported: 'filesystem'."
        )

    def load_dimensions(
        self, schemas: Optional[Dict[str, Any]] = None
    ) -> List[Dimension]:
        """Instantiate plugin classes from config and wrap each in a Dimension.

        If a plugin's ``__init__`` declares a ``schemas`` parameter, the
        config's resolved schema registry is injected automatically.
        """
        registry = schemas if schemas is not None else self.schemas
        instances: List[Dimension] = []
        for entry in self.plugins:
            module_path = entry["module"]
            class_name = entry["class"]
            cfg = dict(entry.get("config", {}) or {})
            override_name = entry.get("name")

            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            sig = inspect.signature(cls.__init__)
            if "schemas" in sig.parameters and "schemas" not in cfg:
                cfg["schemas"] = registry

            plugin: Plugin = cls(**cfg)
            instances.append(Dimension(plugin, name=override_name))
        return instances


def _discover_schemas(directory: Path) -> Dict[str, Any]:
    """Auto-register every ``<name>.spec.json`` under ``directory`` as ``<name>``."""
    if not directory.is_dir():
        return {}
    out: Dict[str, Any] = {}
    for p in sorted(directory.iterdir()):
        if not p.is_file() or not p.name.endswith(".spec.json"):
            continue
        spec_name = p.name[: -len(".spec.json")]
        out[spec_name] = json.loads(p.read_text())
    return out
