"""Dimension — the central object users interact with.

A `Dimension` wraps exactly one `Plugin`. The framework calls dimension
methods (`collect`, `is_applicable`); the dimension delegates to the
plugin under the hood. Plugins do not implement persistence, validation,
or diff — those are framework concerns invoked through the dimension.

Plugins emit one or more envelopes per ``collect()``. The dimension
returns the list of validated envelopes plus the bytes the framework
must externalise to content-addressed asset storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from dimensions.api import CollectionContext, Plugin
from dimensions.validate import validate_envelope


@dataclass
class CollectionResult:
    """One Dimension's contribution to a single capture run."""

    envelopes: List[Dict[str, Any]] = field(default_factory=list)
    # sha256 → (bytes, ext, mime_type) staged by attach_asset()
    pending_assets: Dict[str, Tuple[bytes, str, str]] = field(default_factory=dict)


class Dimension:
    """One named dimension, backed by a single plugin."""

    def __init__(
        self,
        plugin: Plugin,
        *,
        name: Optional[str] = None,
        category: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        if not isinstance(plugin, Plugin):
            raise TypeError(
                f"Dimension expects a Plugin instance, got {type(plugin).__name__}"
            )
        self.plugin = plugin
        self.name = name or plugin.name
        self.category = category or plugin.category
        self.description = description or plugin.description
        if not self.name:
            raise ValueError(
                f"Dimension wrapping {type(plugin).__name__} has no name "
                "(set on plugin class or pass name=...)"
            )
        if not self.category:
            raise ValueError(
                f"Dimension {self.name} has no category "
                "(set on plugin class or pass category=...)"
            )

    def is_applicable(self) -> bool:
        return self.plugin.is_applicable()

    async def collect(self) -> CollectionResult:
        """Run the plugin's collection; return all validated envelopes + assets."""
        ctx = CollectionContext(self.plugin)
        await self.plugin.collect(ctx)
        if not ctx.finalized_envelopes:
            raise RuntimeError(
                f"plugin {type(self.plugin).__name__} did not open any "
                "envelopes inside collect() — every plugin must emit at "
                "least one envelope."
            )
        envelopes: List[Dict[str, Any]] = []
        for env in ctx.finalized_envelopes:
            env["dimension"] = self.name
            env["category"] = self.category
            envelopes.append(validate_envelope(env))
        return CollectionResult(envelopes=envelopes, pending_assets=dict(ctx.pending_assets))
