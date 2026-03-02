"""Typed result models for capability operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProfileResult:
    """Base result for command profile executions."""

    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    command_used: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LintProfileResult(ProfileResult):
    """Result from lint profile execution."""

    files_linted: list[str] = ()


@dataclass(frozen=True, slots=True)
class TestProfileResult(ProfileResult):
    """Result from test profile execution."""

    pattern: str = ""


@dataclass(frozen=True, slots=True)
class BuildProfileResult(ProfileResult):
    """Result from build profile execution."""

    target: str = ""


@dataclass(frozen=True, slots=True)
class RipgrepProfileResult(ProfileResult):
    """Result from ripgrep search profile execution."""

    query: str = ""


@dataclass(frozen=True, slots=True)
class GitStatusResult:
    """Result from git status query."""

    branch: str
    ahead: int
    behind: int
    staged: list[str]
    modified: list[str]
    untracked: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GitDiffResult:
    """Result from git diff query."""

    repo_path: str
    diff_type: str
    file_path: str | None
    commit_refs: list[str] | None
    diff: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GitCheckoutResult:
    """Result from git checkout operation."""

    branch: str
    commit_hash: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GitCommitResult:
    """Result from git commit operation."""

    commit_hash: str | None
    message: str
    files_changed: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FileReadResult:
    """Result from file read operation."""

    content: str
    path: str
    size_bytes: int
    encoding: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FileListResult:
    """Result from file list operation."""

    files: list[dict[str, Any]]
    total_count: int
    directory: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FileSearchResult:
    """Result from file search operation."""

    matches: list[dict[str, Any]]
    query: str
    total_matches: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PatchResult:
    """Result from patch application operation."""

    patched_path: str
    hunks_applied: int
    snapshot_ref: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WebSearchResult:
    """Result from web search operation."""

    query: str
    results: list[dict[str, Any]]
    cached: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SchedulerJobResult:
    """Result from scheduler job operation."""

    job_id: str
    action: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RollbackResult:
    """Result from snapshot rollback operation."""

    snapshot_ref: str
    commit_hash: str
    files_restored: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SnapshotListResult:
    """Result from snapshot list operation."""

    snapshots: list[dict[str, Any]]
    total_count: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PruneSnapshotsResult:
    """Result from snapshot pruning operation."""

    pruned_count: int
    pruned_refs: list[str]
    retained_count: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for backward compatibility."""
        return asdict(self)


# Union type for all capability results
CapabilityResult = (
    LintProfileResult
    | TestProfileResult
    | BuildProfileResult
    | RipgrepProfileResult
    | GitStatusResult
    | GitDiffResult
    | GitCheckoutResult
    | GitCommitResult
    | FileReadResult
    | FileListResult
    | FileSearchResult
    | PatchResult
    | WebSearchResult
    | SchedulerJobResult
    | RollbackResult
    | SnapshotListResult
    | PruneSnapshotsResult
)
