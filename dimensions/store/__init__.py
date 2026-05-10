"""Storage backends for snapshot envelopes."""

from dimensions.store.base import SnapshotBackend
from dimensions.store.filesystem import FilesystemBackend

__all__ = ["SnapshotBackend", "FilesystemBackend"]
