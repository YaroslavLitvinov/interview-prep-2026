"""Storage backend abstract base class."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class SnapshotBackend(ABC):
    """Abstract base for snapshot storage.

    Storage layout (logical, regardless of backend):

        <dimension>/<label>/<envelope_name>.snap.json
        <dimension>/<label>/assets/<sha256><ext>

    A capture run writes one envelope file per emitted envelope plus any
    content-addressed binary artifacts the plugins attached. Backends are
    pluggable; the framework always goes through this interface. Plugins
    never see backends — they hand envelopes to the framework via API.
    """

    # ── envelopes ─────────────────────────────────────────────────────────

    @abstractmethod
    def save(
        self,
        dimension_name: str,
        label: str,
        envelope_name: str,
        envelope: Dict[str, Any],
    ) -> str:
        """Persist an envelope under a (dimension, label, envelope_name) key."""

    @abstractmethod
    def load(
        self, dimension_name: str, label: str, envelope_name: str
    ) -> Dict[str, Any]:
        """Load a previously saved envelope."""

    @abstractmethod
    def envelope_exists(
        self, dimension_name: str, label: str, envelope_name: str
    ) -> bool:
        """Check whether a specific envelope file exists."""

    @abstractmethod
    def label_exists(self, dimension_name: str, label: str) -> bool:
        """Check whether any envelope is stored for this (dimension, label)."""

    # ── inventory ─────────────────────────────────────────────────────────

    @abstractmethod
    def list_labels(self, dimension_name: str) -> List[str]:
        """List all labels for a dimension."""

    @abstractmethod
    def list_envelopes(self, dimension_name: str, label: str) -> List[str]:
        """List envelope names stored under this (dimension, label)."""

    @abstractmethod
    def list_dimensions(self) -> List[str]:
        """List all dimensions that have at least one stored snapshot."""

    # ── assets ────────────────────────────────────────────────────────────

    @abstractmethod
    def save_asset(
        self,
        dimension_name: str,
        label: str,
        sha256: str,
        ext: str,
        content: bytes,
    ) -> str:
        """Persist a content-addressed binary blob; return its asset ref."""

    @abstractmethod
    def read_asset(
        self, dimension_name: str, label: str, sha256: str
    ) -> bytes:
        """Read a previously saved asset by its sha256."""
