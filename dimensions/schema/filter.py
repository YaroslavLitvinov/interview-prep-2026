"""Generic filter spec — Pydantic shape every InjectionProtocol can interpret.

The *shape* is protocol-agnostic; the *selector grammar* is per-protocol.

  browser   → CSS selectors      ("div[testid]", "h1,h2,h3")
  json_file → JSONPath           ("$.records.*.id")
  subprocess→ regex over stdout  ("^ERROR:")

Each protocol's State implementation knows how to apply a FilterSpec
against itself (see ``dimensions/protocols/<name>/filter.py``).

Most filter levels (project, protocol_defaults, dim, scenario) need
only the slim form:

    filter:
      keep:    ["[testid]", "h1,h2,h3", "button"]   # bare selectors
      drop:    ["script", "style"]
      fields:  ["tag", "attributes.data-testid", "text"]
      values:
        computed_style: ["color", "font-size"]

Per-selector field control is available via the long form when needed:

    keep:
      - "[testid]"                                  # string shorthand
      - {selector: "h1", fields: ["tag", "text"]}   # long form
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FilterRule(BaseModel):
    """One match-and-prune rule.

    ``selector`` uses the host protocol's selector grammar. ``fields``
    is optional per-rule override — when set, surviving items matched
    by this rule keep only those fields (overriding the spec-level
    ``fields``).
    """

    model_config = ConfigDict(extra="forbid")

    selector: str
    fields:   Optional[List[str]] = None

    @classmethod
    def _coerce(cls, value: Any) -> "FilterRule":
        """Accept either a bare selector string or a `{selector, fields}` dict."""
        if isinstance(value, FilterRule):
            return value
        if isinstance(value, str):
            return cls(selector=value)
        if isinstance(value, dict):
            return cls.model_validate(value)
        raise TypeError(
            f"FilterRule expects str or dict, got {type(value).__name__}"
        )


class FilterSpec(BaseModel):
    """A complete filter declaration.

    * ``keep`` empty → keep everything that isn't ``drop``-matched.
    * ``keep`` non-empty → whitelist; only matches survive.
    * ``drop`` always removes (wins over ``keep``).
    * ``fields`` (top-level) → per-survivor whitelist applied to every
      kept item. A matching rule's own ``fields`` overrides this.
    * ``values`` → per-dict-field key whitelist (e.g.
      ``computed_style: ["color"]`` keeps only ``color`` inside every
      surviving item's ``computed_style`` dict).
    """

    model_config = ConfigDict(extra="forbid")

    keep:   List[FilterRule] = Field(default_factory=list)
    drop:   List[FilterRule] = Field(default_factory=list)
    fields: List[str] = Field(default_factory=list)
    values: Dict[str, List[str]] = Field(default_factory=dict)

    @field_validator("keep", "drop", mode="before")
    @classmethod
    def _coerce_rules(cls, v: Any) -> List[FilterRule]:
        if v is None:
            return []
        if isinstance(v, (str, dict)):
            return [FilterRule._coerce(v)]
        if isinstance(v, list):
            return [FilterRule._coerce(x) for x in v]
        raise TypeError(
            f"keep/drop must be a list of selectors; got {type(v).__name__}"
        )

    def is_empty(self) -> bool:
        return not (self.keep or self.drop or self.fields or self.values)

    @classmethod
    def merge(cls, *specs: "FilterSpec") -> "FilterSpec":
        """Layered merge.

          * ``keep`` / ``drop``: **concatenate** from all layers.
          * ``fields``: **last non-empty wins** (whitelist is exhaustive).
          * ``values``: **per-key replace** — later layers' keys win.
        """
        keep:   List[FilterRule] = []
        drop:   List[FilterRule] = []
        fields: List[str] = []
        values: Dict[str, List[str]] = {}
        for s in specs:
            if s is None:
                continue
            keep.extend(s.keep)
            drop.extend(s.drop)
            if s.fields:
                fields = list(s.fields)
            for k, v in s.values.items():
                values[k] = list(v)
        return cls(keep=keep, drop=drop, fields=fields, values=values)
