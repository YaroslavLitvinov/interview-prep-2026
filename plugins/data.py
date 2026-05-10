"""Data dimension plugin (project-owned, thin).

Walks one or more JSON files, emitting one envelope per source. Each
source can declare a spec (named, resolved through the framework's schema
registry); when present, the plugin emits ``spec.compiles`` and
``spec.conforms`` rule_check observations.

Configuration (from dimensions.config.yaml):

    config:
      sources:
        - {name: superset, path: prep/superset.k.json, spec: superset}
        - {name: users,    path: data/users.json,      spec: users_spec}

Schemas are auto-discovered from ``schemas_dir`` (every
``<name>.spec.json`` registered as ``<name>``); ``spec`` references one
by name. ``name`` is the envelope key under
``.dimensions/snapshots/data/<label>/<name>.snap.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import jsonschema

from dimensions.api import CollectionContext, Plugin
from dimensions.kinds.data import (
    JsonFileProtocol,
    SpecError,
    compile_spec,
    file_subject_dict,
    walk_json,
)


@dataclass
class DataSource:
    name: str
    path: Path
    spec: Optional[str] = None  # schema-registry name


def _normalize_sources(sources) -> List[Dict[str, Any]]:
    """Accept either a list of dicts or a dict keyed by name.

    Dict shorthand:
        sources: {superset: prep/superset.k.json}                       → list form
        sources: {superset: {path: ..., spec: ...}}                     → list form
        sources: [{name: superset, path: ..., spec: ...}, …]            → unchanged
    """
    if isinstance(sources, dict):
        out: List[Dict[str, Any]] = []
        for k, v in sources.items():
            if isinstance(v, dict):
                out.append({"name": k, **v})
            else:
                out.append({"name": k, "path": v})
        return out
    return list(sources)


class DataPlugin(Plugin):
    name = "data"
    category = "data"
    description = (
        "Walks one or more JSON data files and reports their structural "
        "properties — size, hierarchy depth, key inventory, value-type "
        "distribution, key-frequency histogram, and (when a spec is provided) "
        "conformance to the declared data format."
    )

    def __init__(
        self,
        sources,
        *,
        file_protocol: Optional[JsonFileProtocol] = None,
        schemas: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        super().__init__(sources=sources, **extra)
        self.sources = [
            DataSource(
                name=s["name"],
                path=Path(s["path"]),
                spec=s.get("spec"),
            )
            for s in _normalize_sources(sources)
        ]
        self.file_protocol = file_protocol or JsonFileProtocol()
        self.schemas: Dict[str, Any] = schemas or {}

    def is_applicable(self) -> bool:
        return any(s.path.exists() for s in self.sources)

    async def collect(self, ctx: CollectionContext) -> None:
        async with self.file_protocol as fp:
            for src in self.sources:
                with ctx.envelope(
                    name=src.name,
                    subject=file_subject_dict(src.path),
                ) as env:
                    walk_json(env, src.path)
                    await self._emit_spec(env, fp, src)

    async def _emit_spec(self, env, fp: JsonFileProtocol, src: DataSource) -> None:
        env.boolean(
            "spec.declared",
            "A data-format spec was provided for this source",
            value=src.spec is not None,
        )
        if src.spec is None:
            return

        spec_doc = self.schemas.get(src.spec)
        if spec_doc is None:
            env.rule_check(
                "spec.compiles",
                "Spec resolves through the registry and compiles to JSON Schema",
                passed=False,
                violations=[f"unknown spec name: {src.spec!r}"],
                checked_count=1,
            )
            return

        try:
            schema = compile_spec(spec_doc)
        except SpecError as e:
            env.rule_check(
                "spec.compiles",
                "Spec resolves through the registry and compiles to JSON Schema",
                passed=False,
                violations=[f"{type(e).__name__}: {e}"],
                checked_count=1,
            )
            return

        env.rule_check(
            "spec.compiles",
            "Spec resolves through the registry and compiles to JSON Schema",
            passed=True,
            checked_count=1,
        )

        try:
            data = await fp.read_json(src.path)
        except Exception as e:  # noqa: BLE001
            env.rule_check(
                "spec.conforms",
                "Source data conforms to the declared spec",
                passed=False,
                violations=[f"could not parse source: {e}"],
                checked_count=1,
            )
            return

        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
        env.rule_check(
            "spec.conforms",
            "Source data conforms to the declared spec",
            passed=not errors,
            violations=[
                f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
                for e in errors
            ],
            checked_count=1,
        )
