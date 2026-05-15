"""Generate JSON Schema files from the Pydantic models.

Run this whenever the schema models change:

    python3 -m dimensions.schema._generate

Outputs land in `dimensions/schema/_generated/` and are the canonical
contract for cross-language plugin authors. Three flavors are written:

- `observation.schema.json` — the canonical catalog of observation kinds.
  All other files `$ref` into this one for shared shapes.
- `<name>.envelope.schema.json` — per-dimension envelope. Subject types
  defined locally; observation kinds referenced from observation.schema.json.
- `envelope.schema.json` — thin discriminated union that `$ref`s the
  per-dimension files by `category`. Use this when consuming snapshots
  whose dimension is not known up front.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

# Importing `dimensions.protocols` triggers per-kind registration so the union
# and per-kind models all exist before we ask Pydantic for schemas.
import dimensions.protocols as _kinds  # noqa: F401  (side-effect import)

from pydantic import TypeAdapter

from dimensions.protocols import PROTOCOL_REGISTRY
from dimensions.schema.envelope import EnvelopeAdapter
from dimensions.schema.observation import ObservationAdapter


_GENERATED_DIR = Path(__file__).parent / "_generated"

# Shared observation $defs live canonically in observation.schema.json.
# Every other generated file references them across files instead of inlining.
_SHARED_OBSERVATION_DEFS = {
    "ScalarObservation",
    "BooleanObservation",
    "RuleCheckObservation",
    "SetObservation",
    "DistributionObservation",
    "HistogramObservation",
    "HistogramItem",
    "PayloadObservation",
}

_OBSERVATION_FILE = "observation.schema.json"


_PURPOSES = {
    "observation.schema.json": (
        "Canonical catalog of observation kinds (scalar, boolean, rule_check, "
        "set, distribution, histogram). Discriminated by `kind`. All envelope "
        "schemas $ref these definitions instead of inlining them."
    ),
    "envelope.schema.json": (
        "Thin discriminated union over every dimension's envelope, keyed by "
        "`category`. Use this to validate a snapshot when the producing "
        "dimension is not known up front (generic loaders, renderers, diff "
        "engines). Members are $ref'd from per-dimension files."
    ),
    "data.envelope.schema.json": (
        "Envelope contract for the `data` dimension: structural observations "
        "of a JSON file (size, depth, key frequency, value-type distribution). "
        "Subject is a FileSubject. Observation kinds are $ref'd from "
        "observation.schema.json."
    ),
    "visual.envelope.schema.json": (
        "Envelope contract for the `visual` dimension: observations captured "
        "from rendering a URL (DOM tag distribution, headings, a11y rule "
        "checks, viewport, status). Subject is a UrlSubject. Observation "
        "kinds are $ref'd from observation.schema.json."
    ),
}


def _rewrite_shared_refs(node: Any, target_file: str) -> None:
    """Rewrite local `$ref: #/$defs/<SharedDef>` to point across files."""
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if (
                key == "$ref"
                and isinstance(value, str)
                and value.startswith("#/$defs/")
                and value.split("/")[-1] in _SHARED_OBSERVATION_DEFS
            ):
                node[key] = f"{target_file}#/$defs/{value.split('/')[-1]}"
            else:
                _rewrite_shared_refs(value, target_file)
    elif isinstance(node, list):
        for item in node:
            _rewrite_shared_refs(item, target_file)


def _strip_shared_defs(schema: Dict[str, Any]) -> None:
    defs = schema.get("$defs")
    if not defs:
        return
    for name in list(defs.keys()):
        if name in _SHARED_OBSERVATION_DEFS:
            del defs[name]
    if not defs:
        del schema["$defs"]


def _build_thin_union() -> Dict[str, Any]:
    """Hand-roll the union schema as cross-file $refs to per-dimension files."""
    mapping = {
        name: f"{name}.envelope.schema.json"
        for name in PROTOCOL_REGISTRY
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Envelope",
        "discriminator": {
            "propertyName": "category",
            "mapping": mapping,
        },
        "oneOf": [{"$ref": ref} for ref in mapping.values()],
    }


def main() -> int:
    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Canonical observation catalog — kept whole.
    observation_schema = ObservationAdapter.json_schema()

    # 2. Per-dimension envelopes — strip shared defs, rewrite refs across files.
    per_dimension: Dict[str, Dict[str, Any]] = {}
    for name, spec in PROTOCOL_REGISTRY.items():
        adapter = TypeAdapter(spec["envelope_cls"])
        schema = adapter.json_schema()
        _rewrite_shared_refs(schema, _OBSERVATION_FILE)
        _strip_shared_defs(schema)
        per_dimension[f"{name}.envelope.schema.json"] = schema

    # 3. Union envelope — thin, references per-dimension files only.
    union_schema = _build_thin_union()

    schemas: Dict[str, Dict[str, Any]] = {
        "observation.schema.json": observation_schema,
        "envelope.schema.json": union_schema,
        **per_dimension,
    }

    # Annotate every file with its purpose and dialect so readers and
    # cross-file $ref resolvers know what they're looking at.
    for filename, schema in schemas.items():
        schema.setdefault(
            "$schema", "https://json-schema.org/draft/2020-12/schema"
        )
        if filename in _PURPOSES:
            schema["description"] = _PURPOSES[filename]

    for filename, schema in schemas.items():
        path = _GENERATED_DIR / filename
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
