"""Public API for plugin authors.

Plugins import from this module — never from internal framework internals.
The contract is:

    from dimensions.api import Plugin

    class MyPlugin(Plugin):
        name = "my_dim"
        category = "data"   # or visual / web / cli / performance

        def __init__(self, **config):
            super().__init__(**config)
            ...                                      # capture project config

        def is_applicable(self):
            return True                              # optional override

        def collect(self, ctx):
            with ctx.envelope(subject={...}) as env:
                env.scalar("counts.users", "Total users", 42)
                env.rule_check("schema.required_fields", "...",
                               passed=True, checked_count=42)

The framework owns persistence, validation, diff, and rendering. The plugin
owns the dimension-specific knowledge of WHAT to observe and HOW to drive
the framework primitives to obtain it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Sequence

from dimensions import observation as obs


__all__ = ["CollectionContext", "EnvelopeBuilder", "Plugin", "obs"]


# Common MIME → extension mapping for content-addressed asset storage.
_MIME_TO_EXT: Dict[str, str] = {
    "image/png":             ".png",
    "image/jpeg":            ".jpg",
    "image/webp":            ".webp",
    "image/svg+xml":         ".svg",
    "text/html":             ".html",
    "text/plain":            ".txt",
    "application/json":      ".json",
    "application/octet-stream": ".bin",
    "application/pdf":       ".pdf",
}


# ── EnvelopeBuilder ────────────────────────────────────────────────────────


class EnvelopeBuilder:
    """Accumulates observations + subject for one envelope.

    The plugin receives an `EnvelopeBuilder` from `ctx.envelope(...)` and
    pushes observations onto it. The runner finalizes the envelope on
    context exit. Plugins do not construct this directly.
    """

    def __init__(
        self,
        dimension: str,
        protocol: str,
        subject: Dict[str, Any],
        *,
        envelope_name: str = "main",
    ):
        self.dimension = dimension
        self.protocol = protocol
        self.subject = dict(subject)
        self.observations: List[Dict[str, Any]] = []
        self._envelope_name = envelope_name
        self._pending_assets: Dict[str, "tuple[bytes, str, str]"] = {}

    def _stamp_entity_id(self, ob: Dict[str, Any]) -> Dict[str, Any]:
        """Stamp a content-derived stable id onto an observation.

        The id hashes (dimension, envelope, observation id, kind) — and
        for payloads, the schema as well — so the same logical entity
        gets the same id across recaptures. Comments anchored to
        ``entity_id`` therefore survive re-collect.
        """
        import hashlib
        parts = [
            self.dimension or "",
            self._envelope_name or "",
            str(ob.get("id") or ""),
            str(ob.get("kind") or ""),
            str(ob.get("payload_schema") or ""),
        ]
        digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
        ob["entity_id"] = f"e_{digest[:16]}"
        return ob

    def _append(self, ob: Dict[str, Any]) -> None:
        self.observations.append(self._stamp_entity_id(ob))

    # ── observation builders (push-style) ────────────────────────────────

    def scalar(
        self,
        id: str,
        label: str,
        value: Any,
        unit: Optional[str] = None,
        *,
        required: bool = False,
    ) -> None:
        self._append(
            obs.scalar(id, label, value, unit=unit, required=required)
        )

    def boolean(
        self, id: str, label: str, value: bool, *, required: bool = False
    ) -> None:
        self._append(
            obs.boolean(id, label, value, required=required)
        )

    def rule_check(
        self,
        id: str,
        label: str,
        *,
        passed: bool,
        violations: Optional[Sequence[Any]] = None,
        sample_size: int = 20,
        checked_count: Optional[int] = None,
        required: bool = False,
    ) -> None:
        self._append(
            obs.rule_check(
                id,
                label,
                passed=passed,
                violations=list(violations or []),
                sample_size=sample_size,
                checked_count=checked_count,
                required=required,
            )
        )

    def set(
        self, id: str, label: str, items, *, required: bool = False
    ) -> None:
        self._append(
            obs.set_observation(id, label, items, required=required)
        )

    def distribution(
        self,
        id: str,
        label: str,
        buckets: Dict[str, int],
        *,
        required: bool = False,
    ) -> None:
        self._append(
            obs.distribution(id, label, buckets, required=required)
        )

    def histogram(
        self,
        id: str,
        label: str,
        counts: Dict[str, int],
        top_n: int = 30,
        *,
        required: bool = False,
    ) -> None:
        self._append(
            obs.histogram(id, label, counts, top_n=top_n, required=required)
        )

    def payload(
        self,
        id: str,
        label: str,
        payload_schema: str,
        data: Any,
        *,
        required: bool = False,
    ) -> None:
        self._append(
            obs.payload(id, label, payload_schema, data, required=required)
        )

    # ── asset attachment ───────────────────────────────────────────────

    def attach_asset(
        self,
        content: bytes,
        mime_type: str,
        *,
        name: Optional[str] = None,
        suffix: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Stage a binary blob for content-addressed storage.

        Returns a metadata dict (sha256, ref, size_bytes, mime_type) that
        the plugin embeds into a `payload` observation. The framework
        externalises the bytes into ``<dim>/<label>/assets/<sha256><ext>``
        when the envelope is persisted; the JSON envelope itself stays
        binary-free.
        """
        import hashlib
        sha = hashlib.sha256(content).hexdigest()
        ext = suffix or _MIME_TO_EXT.get(mime_type, "")
        ref = f"assets/{sha}{ext}"
        meta = {
            "sha256": sha,
            "ref": ref,
            "size_bytes": len(content),
            "mime_type": mime_type,
        }
        if name is not None:
            meta["name"] = name
        self._pending_assets[sha] = (content, ext, mime_type)
        return meta

    @property
    def pending_assets(self) -> Dict[str, "tuple[bytes, str, str]"]:
        return self._pending_assets

    # ── name / lifecycle ───────────────────────────────────────────────

    @property
    def envelope_name(self) -> str:
        return self._envelope_name

    # ── runner-facing serialization ──────────────────────────────────────

    def _to_envelope(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "protocol":  self.protocol,
            "envelope_name": self._envelope_name,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "subject": self.subject,
            "observations": self.observations,
        }


# ── CollectionContext ──────────────────────────────────────────────────────


class CollectionContext:
    """Per-collection-run handle a plugin uses inside `collect(ctx)`.

    Single responsibility: manage envelope lifecycles. Filesystem, HTTP,
    and process work are the plugin's job — use stdlib (`pathlib`, `json`,
    `urllib`, `subprocess`) directly, or accept an injectable dependency
    (`BaseInjectionProtocol`) for anything that benefits from being mocked
    or swapped.

    A plugin may open an arbitrary number of envelopes inside one
    ``collect()`` call. Each is identified by a ``name`` key (unique
    within the collection run) and is appended to ``finalized_envelopes``
    on context exit.
    """

    def __init__(self, plugin: "Plugin"):
        self._plugin = plugin
        self.finalized_envelopes: List[Dict[str, Any]] = []
        self.pending_assets: Dict[str, "tuple[bytes, str, str]"] = {}
        self._open_names: set = set()

    @contextmanager
    def envelope(
        self,
        *,
        name: str,
        subject: Dict[str, Any],
        dimension: Optional[str] = None,
    ) -> Iterator[EnvelopeBuilder]:
        """Open a named envelope. On normal exit it is finalized; on
        exception it is dropped and the exception propagates."""
        if name in self._open_names:
            raise RuntimeError(
                f"plugin {self._plugin.name} reused envelope name {name!r}; "
                "names must be unique within one collect() call."
            )
        self._open_names.add(name)
        eb = EnvelopeBuilder(
            dimension=dimension or self._plugin.name,
            protocol=getattr(self._plugin, "protocol", "")
                     or getattr(self._plugin, "category", ""),
            subject=subject,
            envelope_name=name,
        )
        yield eb
        self.finalized_envelopes.append(eb._to_envelope())
        # Hoist staged assets up to the context for the framework to
        # externalise at persistence time.
        for sha, payload in eb.pending_assets.items():
            self.pending_assets.setdefault(sha, payload)


# ── Plugin ABC ────────────────────────────────────────────────────────────


class Plugin(ABC):
    """Base class for collectors. One plugin is attached to one Dimension.

    Plugins live in the project (typically under `/workspace/plugins/`)
    and are thin: they wire project-side configuration to framework
    primitives via the `CollectionContext`. They do not deal with
    persistence, diff, or rendering — those are framework concerns.

    Plugins declare their identity through the class attributes
    ``name`` (dimension label) and ``protocol`` (the InjectionProtocol
    kind they use — "browser" / "json_file" / "subprocess" / …). The
    wrapping `Dimension` reads them by default and may override them.
    """

    name: str = ""
    protocol: str = ""        # "browser" | "json_file" | "subprocess" | …
    description: str = ""

    def __init__(self, **config: Any) -> None:
        self._config = dict(config)

    def is_applicable(self) -> bool:
        """Return True if this plugin can run with its current configuration.

        Default: always applicable. Override for plugins whose source may
        not exist (e.g., a Data plugin checking optional files).
        """
        return True

    @abstractmethod
    async def collect(self, ctx: CollectionContext) -> None:
        """Walk the source(s) and emit observations via ``ctx.envelope(...)``.

        Implementations open one or more envelopes — each via
        ``ctx.envelope(name=..., subject=..., ...)`` as a context manager
        — and push observations onto the yielded `EnvelopeBuilder`. The
        framework finalises, validates, and persists each on exit.
        """
