"""Base for injectable dependencies a plugin reaches outside itself.

Plugins that need an external system (a browser, an HTTP client, a SQL
session, a process supervisor) accept a subclass of
`BaseInjectionProtocol` in their constructor and use it as an async
context manager. This keeps the plugin's logic side-effect-free with
respect to that system, lets tests substitute a fake, and lets engines be
swapped without touching plugin code.

Concrete protocols inherit from `BaseInjectionProtocol` (for the
lifecycle + default comparator) and from a domain abstract subclass that
adds the operations a plugin actually calls (e.g.,
`BrowserProtocol.render(url)` or `JsonFileProtocol.read_json(path)`).
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Dict, Optional


class BaseInjectionProtocol(ABC):
    """Abstract base for injectable plugin dependencies.

    The contract is intentionally tiny:

    - ``open()``  — async; acquire whatever the implementation needs.
    - ``close()`` — async; release it.
    - ``__aenter__`` / ``__aexit__`` — bind the lifecycle to ``async with``.
    - ``compare(before, after, envelope_type)`` — default structural diff;
      concrete subclasses override for richer semantics (per-pixel image
      diff, JSON-path-aware diff, etc).

    Subclasses add domain methods. Tests substitute a fake by writing
    another subclass — no patching, no monkeypatching, no global state.
    """

    name: str = ""

    async def open(self) -> None:
        """Acquire resources. Default: no-op."""

    async def close(self) -> None:
        """Release resources. Default: no-op."""

    async def __aenter__(self) -> "BaseInjectionProtocol":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        await self.close()
        return False

    # ── default comparator ──────────────────────────────────────────────

    def compare(
        self,
        before: Any,
        after: Any,
        envelope_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Default structural comparator.

        Returns ``None`` when before/after are equal, otherwise a dict
        describing the difference. Subclasses override to provide
        domain-specific comparison (image pixel-diff, JSON path-keyed
        diff, etc); ``envelope_type`` lets one protocol dispatch across
        multiple envelope shapes (e.g. a browser protocol comparing both
        ``dom`` and ``screenshot`` envelopes).
        """
        if before == after:
            return None
        return {"raw": True, "before": before, "after": after}
