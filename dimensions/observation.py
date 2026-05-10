"""Builders for the six observation kinds.

Plugins call these helpers to produce well-formed observations. Each builder
returns a plain dict that conforms to the corresponding Pydantic model in
`dimensions.schema.observation`.

Every builder accepts an optional ``required: bool`` flag that marks the
observation as load-bearing for the snapshot's overall verdict. The flag is
omitted from the dict when False (the schema default) to keep snapshots
compact; the Pydantic model fills it in on validation either way.
"""

from typing import Any, Dict, Iterable, List, Optional


SCALAR = "scalar"
BOOLEAN = "boolean"
RULE_CHECK = "rule_check"
SET = "set"
DISTRIBUTION = "distribution"
HISTOGRAM = "histogram"
PAYLOAD = "payload"

KNOWN_KINDS = frozenset({
    SCALAR, BOOLEAN, RULE_CHECK, SET, DISTRIBUTION, HISTOGRAM, PAYLOAD,
})


def _maybe_required(obs: Dict[str, Any], required: bool) -> Dict[str, Any]:
    if required:
        obs["required"] = True
    return obs


def scalar(
    id: str,
    label: str,
    value: Any,
    unit: Optional[str] = None,
    *,
    required: bool = False,
) -> Dict[str, Any]:
    obs: Dict[str, Any] = {"id": id, "kind": SCALAR, "label": label, "value": value}
    if unit is not None:
        obs["unit"] = unit
    return _maybe_required(obs, required)


def boolean(
    id: str, label: str, value: bool, *, required: bool = False
) -> Dict[str, Any]:
    return _maybe_required(
        {"id": id, "kind": BOOLEAN, "label": label, "value": bool(value)},
        required,
    )


def rule_check(
    id: str,
    label: str,
    passed: bool,
    violations: Optional[Iterable[Any]] = None,
    sample_size: int = 20,
    checked_count: Optional[int] = None,
    *,
    required: bool = False,
) -> Dict[str, Any]:
    items: List[Any] = list(violations or [])
    obs: Dict[str, Any] = {
        "id": id,
        "kind": RULE_CHECK,
        "label": label,
        "passed": bool(passed),
        "violations_count": len(items),
        "violations_sample": items[:sample_size],
    }
    if checked_count is not None:
        obs["checked_count"] = int(checked_count)
    return _maybe_required(obs, required)


def set_observation(
    id: str, label: str, items: Iterable[str], *, required: bool = False
) -> Dict[str, Any]:
    return _maybe_required(
        {
            "id": id,
            "kind": SET,
            "label": label,
            "items": sorted({str(item) for item in items}),
        },
        required,
    )


def distribution(
    id: str,
    label: str,
    buckets: Dict[str, int],
    *,
    required: bool = False,
) -> Dict[str, Any]:
    return _maybe_required(
        {
            "id": id,
            "kind": DISTRIBUTION,
            "label": label,
            "buckets": dict(sorted(buckets.items())),
        },
        required,
    )


def histogram(
    id: str,
    label: str,
    counts: Dict[str, int],
    top_n: int = 30,
    *,
    required: bool = False,
) -> Dict[str, Any]:
    pairs = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return _maybe_required(
        {
            "id": id,
            "kind": HISTOGRAM,
            "label": label,
            "total": sum(counts.values()),
            "unique": len(counts),
            "top_n": [{"key": k, "count": v} for k, v in pairs[:top_n]],
        },
        required,
    )


def payload(
    id: str,
    label: str,
    payload_schema: str,
    data: Any,
    *,
    required: bool = False,
) -> Dict[str, Any]:
    """A free-form structured observation.

    `payload_schema` names the shape of `data` (e.g. ``dom_tree``,
    ``screenshot``, ``comparison``). The framework dispatches diff and
    render on this discriminator. Unknown values fall back to a generic
    JSON dump.

    `data` is opaque to the framework — any JSON-serializable shape is
    valid. This is the kind to use when the existing fixed-shape kinds
    (scalar/boolean/rule_check/set/distribution/histogram) cannot carry
    the structure you need.
    """
    return _maybe_required(
        {
            "id": id,
            "kind": PAYLOAD,
            "label": label,
            "payload_schema": payload_schema,
            "data": data,
        },
        required,
    )
