"""Data-format spec → JSON Schema compiler.

The spec is a small, nested DSL that mirrors the shape of the data being
described. Every node has the same structure:

    {
      "type":     "<scalar | object | array>",
      "required": <bool>,                       # consumed by the parent
      "enum":     [...],                        # optional value constraint
      "pattern":  "...",                        # strings only
      "min":      <number>,                     # numbers: minimum value
                                                # strings: minLength
                                                # arrays:  minItems
      "max":      <number>,                     # symmetric
      "fields":   { <name>: <node>, ... },      # only when type == object
      "*":        <node>                        # only when type == array
    }

Reserved keys at every level: type, required, enum, pattern, min, max,
fields, *. Anything else raises a SpecError so typos don't silently turn
into ignored constraints.
"""

from __future__ import annotations

from typing import Any, Dict, List


_SCALAR_TYPES = {"string", "integer", "number", "boolean"}
_RESERVED = {"type", "required", "enum", "pattern", "min", "max", "fields", "*"}


class SpecError(ValueError):
    """The user-supplied spec is malformed."""


def compile_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Compile a spec node into a Draft 2020-12 JSON Schema."""
    schema = _compile(spec, path="$")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


def _compile(node: Any, *, path: str) -> Dict[str, Any]:
    if not isinstance(node, dict):
        raise SpecError(f"{path}: node must be an object, got {type(node).__name__}")

    unknown = set(node.keys()) - _RESERVED
    if unknown:
        raise SpecError(
            f"{path}: unknown key(s) {sorted(unknown)}; allowed: {sorted(_RESERVED)}"
        )

    t = node.get("type")
    if t is None:
        raise SpecError(f"{path}: missing required key 'type'")

    if t in _SCALAR_TYPES:
        return _compile_scalar(node, t, path=path)
    if t == "object":
        return _compile_object(node, path=path)
    if t == "array":
        return _compile_array(node, path=path)
    raise SpecError(
        f"{path}: unsupported type {t!r}; expected one of "
        f"{sorted(_SCALAR_TYPES | {'object', 'array'})}"
    )


def _compile_scalar(node: Dict[str, Any], t: str, *, path: str) -> Dict[str, Any]:
    if "fields" in node:
        raise SpecError(f"{path}: 'fields' only valid on type='object'")
    if "*" in node:
        raise SpecError(f"{path}: '*' only valid on type='array'")
    schema: Dict[str, Any] = {"type": t}
    if "enum" in node:
        schema["enum"] = list(node["enum"])
    if "pattern" in node:
        if t != "string":
            raise SpecError(f"{path}: 'pattern' only valid on type='string'")
        schema["pattern"] = node["pattern"]
    if "min" in node:
        schema[_min_key(t)] = node["min"]
    if "max" in node:
        schema[_max_key(t)] = node["max"]
    return schema


def _min_key(t: str) -> str:
    return "minLength" if t == "string" else "minimum"


def _max_key(t: str) -> str:
    return "maxLength" if t == "string" else "maximum"


def _compile_object(node: Dict[str, Any], *, path: str) -> Dict[str, Any]:
    if "*" in node:
        raise SpecError(f"{path}: '*' only valid on type='array'")
    fields = node.get("fields") or {}
    if not isinstance(fields, dict):
        raise SpecError(f"{path}.fields: must be an object")

    properties: Dict[str, Any] = {}
    required: List[str] = []
    for name, child in fields.items():
        if not isinstance(child, dict):
            raise SpecError(
                f"{path}.fields.{name}: must be an object (a spec node)"
            )
        properties[name] = _compile(child, path=f"{path}.fields.{name}")
        if child.get("required"):
            required.append(name)

    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _compile_array(node: Dict[str, Any], *, path: str) -> Dict[str, Any]:
    if "fields" in node:
        raise SpecError(f"{path}: 'fields' only valid on type='object'")
    items_node = node.get("*")
    if items_node is None:
        raise SpecError(f"{path}: array spec must define '*' for items")
    schema: Dict[str, Any] = {
        "type": "array",
        "items": _compile(items_node, path=f"{path}.*"),
    }
    if "min" in node:
        schema["minItems"] = node["min"]
    if "max" in node:
        schema["maxItems"] = node["max"]
    return schema
