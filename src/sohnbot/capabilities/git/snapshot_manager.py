"""Git snapshot manager for creating snapshot branches before modifications."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class GitCapabilityError(Exception):
    """Structured error for git capability operations."""

    code: str
    message: str
    details: dict[str, Any] | None = None
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details or {},
            "retryable": self.retryable,
        }


class SnapshotManager:
    """Creates git snapshot branches at HEAD before modification operations."""

    def find_repo_root(self, file_path: str) -> str:
        """
        Walk up from file_path to find the first directory containing .git/.

        Args:
            file_path: Path to the target file (or directory)

        Returns:
            Absolute path string of the git repository root

        Raises:
            GitCapabilityError: If no .git directory found
        """
        current = Path(file_path).resolve()
        # If given a file path, start from its parent directory
        if current.is_file():
            current = current.parent

        while True:
            if (current / ".git").exists():
                return str(current)
            parent = current.parent
            if parent == current:
                # Reached filesystem root
                break
            current = parent

        raise GitCapabilityError(
            code="not_a_git_repo",
            message="No git repository found for the given path",
            details={"path": file_path},
            retryable=False,
        )

    async def create_snapshot(
        self,
        repo_path: str,
        operation_id: str,
        timeout_seconds: int = 10,
    ) -> str:
        """
        Create a git snapshot branch at HEAD without switching to it.

        Branch naming: snapshot/edit-YYYY-MM-DD-HHMM
        On name collision (same minute): appends -{operation_id[:4]} suffix.

        Args:
            repo_path: Absolute path to the git repository root
            operation_id: UUID tracking ID (used for collision suffix)
            timeout_seconds: Maximum time for git command

        Returns:
            Snapshot branch name created

        Raises:
            GitCapabilityError: On git failure, timeout, or missing git CLI
        """
        branch_name = (
            f"snapshot/edit-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M')}"
        )

        result = await self._run_git_branch(
            repo_path, branch_name, timeout_seconds, required=False
        )

        if result is None:
            # Name collision — append operation_id[:4] suffix and retry
            branch_name = f"{branch_name}-{operation_id[:4]}"
            await self._run_git_branch(
                repo_path, branch_name, timeout_seconds, required=True
            )

        logger.info(
            "snapshot_created",
            repo_path=repo_path,
            operation_id=operation_id,
            snapshot_ref=branch_name,
        )

        return branch_name

    async def _run_git_branch(
        self,
        repo_path: str,
        branch_name: str,
        timeout_seconds: int,
        required: bool,
    ) -> str | None:
        """
        Execute `git -C <repo_path> branch <branch_name>`.

        Returns branch_name on success, None on name collision
        (when required=False). Raises GitCapabilityError on other failures.
        """
        cmd = ["git", "-C", repo_path, "branch", branch_name]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise GitCapabilityError(
                code="git_not_found",
                message="git CLI is required for snapshot operations",
                details={"repo_path": repo_path},
                retryable=False,
            ) from exc

        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise GitCapabilityError(
                code="snapshot_timeout",
                message=f"Git snapshot creation timed out after {timeout_seconds}s",
                details={"repo_path": repo_path, "branch_name": branch_name},
                retryable=True,
            ) from exc

        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            if "already exists" in stderr_text and not required:
                return None  # Signal collision to caller
            raise GitCapabilityError(
                code="snapshot_creation_failed",
                message="Failed to create snapshot branch",
                details={
                    "repo_path": repo_path,
                    "branch_name": branch_name,
                    "stderr": stderr_text,
                },
                retryable=False,
            )

        return branch_name
