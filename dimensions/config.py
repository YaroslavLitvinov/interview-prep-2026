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
    scenario_roots: List[str] = field(
        default_factory=lambda: [
            "tests/dimensions/scenarios",
            "tests/dimensions/flows",
        ]
    )
    vars: Dict[str, str] = field(default_factory=dict)
    protocol_defaults: Dict[str, Any] = field(default_factory=dict)
    project_filter: Optional[Any] = None

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
            scenario_roots=list(
                data.get("scenario_roots", [
                    "tests/dimensions/scenarios",
                    "tests/dimensions/flows",
                ])
            ),
            vars=dict(data.get("vars") or {}),
            protocol_defaults=dict(data.get("protocol_defaults") or {}),
            project_filter=data.get("filter"),
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

    def root_filter(self):
        """Project-level FilterSpec (top of the merge chain)."""
        from dimensions.schema.filter import FilterSpec
        if self.project_filter:
            return FilterSpec.model_validate(self.project_filter)
        return None

    def protocol_filter(self, protocol_name: str):
        """FilterSpec declared in ``protocol_defaults.<protocol>.filter``."""
        from dimensions.schema.filter import FilterSpec
        defaults = (self.protocol_defaults or {}).get(protocol_name) or {}
        raw = defaults.get("filter") or {}
        return FilterSpec.model_validate(raw) if raw else None

    def dim_filter(self, dim_name: str):
        """FilterSpec declared on a specific ``dimensions[]`` entry."""
        from dimensions.schema.filter import FilterSpec
        for entry in self.plugins:
            if entry.get("name") == dim_name:
                raw = entry.get("filter") or (entry.get("config") or {}).get("filter")
                if raw:
                    return FilterSpec.model_validate(raw)
        return None

    def plugin_urls(self, plugin_name: str) -> Dict[str, str]:
        """Return the substitution namespace for ``${name}`` placeholders
        in scenarios.

        Resolution order (first hit wins):
          1. Top-level ``vars:`` (global, shared across every dimension).
          2. Legacy ``plugins[<name>].config.urls`` (per-plugin namespace
             from older configs — kept for back-compat; new configs put
             everything under ``vars``).
        """
        out: Dict[str, str] = {}
        # Legacy first, then vars override.
        for entry in self.plugins:
            if entry.get("name") == plugin_name:
                urls = (entry.get("config") or {}).get("urls") or {}
                out.update({str(k): str(v) for k, v in urls.items()})
        for k, v in self.vars.items():
            out[str(k)] = str(v)
        return out

    def plugin_classes(self) -> Dict[str, type]:
        """Resolve every configured plugin entry to its class, keyed by
        the registered plugin name. Used by the scenario replay harness
        to look up a plugin from ``scenario.plugin`` without hardcoding.
        """
        out: Dict[str, type] = {}
        for entry in self.plugins:
            module = importlib.import_module(entry["module"])
            cls = getattr(module, entry["class"])
            name = entry.get("name") or getattr(cls, "name", None)
            if not name:
                raise ValueError(
                    f"plugin entry {entry!r} has no name (set 'name:' in "
                    f"config or `name` class attribute on {cls.__name__})"
                )
            if name in out:
                raise ValueError(f"duplicate plugin name in config: {name!r}")
            out[name] = cls
        return out

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
