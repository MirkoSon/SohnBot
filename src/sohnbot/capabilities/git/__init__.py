"""Git capability package."""

from .snapshot_manager import GitCapabilityError, SnapshotManager

__all__ = ["SnapshotManager", "GitCapabilityError"]
