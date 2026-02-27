"""Git snapshot manager for creating snapshot branches before modifications."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
        # Start from parent if current is not a directory
        # (handles existing files, non-existent paths, and symlinks to files)
        if not current.is_dir():
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

    def list_snapshots(self, repo_path: str) -> list[dict[str, Any]]:
        """
        List all snapshot branches in the repository.

        Args:
            repo_path: Absolute path to git repository root

        Returns:
            List of dicts: [{"ref": "snapshot/edit-...", "timestamp": "Feb 27, 2026 14:30 UTC"}, ...]
            Sorted by timestamp descending (newest first)

        Raises:
            GitCapabilityError: If git command fails
        """
        import subprocess

        cmd = ["git", "-C", repo_path, "branch", "--list", "snapshot/*"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except FileNotFoundError as exc:
            raise GitCapabilityError(
                code="git_not_found",
                message="git CLI is required for snapshot operations",
                details={"repo_path": repo_path},
                retryable=False,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise GitCapabilityError(
                code="list_snapshots_failed",
                message="Git list snapshots command timed out",
                details={"repo_path": repo_path},
                retryable=True,
            ) from exc

        if result.returncode != 0:
            raise GitCapabilityError(
                code="list_snapshots_failed",
                message="Failed to list snapshot branches",
                details={
                    "repo_path": repo_path,
                    "stderr": result.stderr.decode("utf-8", errors="replace").strip(),
                },
                retryable=False,
            )

        # Parse output: lines like "  snapshot/edit-YYYY-MM-DD-HHMM" or "  snapshot/edit-YYYY-MM-DD-HHMM-suffix"
        output = result.stdout.decode("utf-8", errors="replace").strip()
        if not output:
            return []

        snapshots = []
        for line in output.split("\n"):
            branch_name = line.strip()
            if not branch_name:
                continue

            # Parse timestamp from branch name: snapshot/edit-YYYY-MM-DD-HHMM(-suffix)?
            try:
                dt = self._parse_snapshot_datetime(branch_name)
                formatted = dt.strftime("%b %d, %Y %H:%M UTC")
                snapshots.append({
                    "ref": branch_name,
                    "timestamp": formatted,
                    "_datetime": dt,  # For sorting
                })
            except (IndexError, ValueError) as exc:
                # Keep unparseable branches visible for observability and pruning safety.
                logger.warning(
                    "snapshot_name_parse_failed",
                    branch_name=branch_name,
                    error=str(exc),
                )
                snapshots.append({
                    "ref": branch_name,
                    "timestamp": "Unknown",
                    "_datetime": datetime.min.replace(tzinfo=timezone.utc),
                })

        # Sort by datetime descending (newest first)
        snapshots.sort(key=lambda x: x["_datetime"], reverse=True)

        # Remove sorting helper
        for snap in snapshots:
            del snap["_datetime"]

        logger.info(
            "snapshots_listed",
            repo_path=repo_path,
            snapshot_count=len(snapshots),
        )

        return snapshots

    async def prune_snapshots(
        self,
        repo_path: str,
        retention_days: int = 30,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        """Prune snapshot branches older than retention_days."""
        if retention_days <= 0:
            raise GitCapabilityError(
                code="invalid_retention_days",
                message="Retention days must be greater than 0",
                details={"retention_days": retention_days},
                retryable=False,
            )

        start_time = datetime.now(timezone.utc)
        deadline = start_time + timedelta(seconds=timeout_seconds)
        snapshots = await self._list_snapshots_for_prune(repo_path, deadline)
        if not snapshots:
            return {"pruned_count": 0, "pruned_refs": [], "retained_count": 0}

        try:
            _, stdout_text, _ = await self._run_git_async(
                ["git", "-C", repo_path, "branch", "--show-current"],
                repo_path=repo_path,
                deadline=deadline,
                timeout_code="prune_timeout",
            )
            current_branch = stdout_text.strip()
        except GitCapabilityError as exc:
            if exc.code in {"prune_timeout", "git_not_found"}:
                raise
            current_branch = ""

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        pruned_refs: list[str] = []
        retained_count = 0

        for snapshot in snapshots:
            ref = snapshot["ref"]
            if ref == current_branch:
                retained_count += 1
                logger.info("snapshot_prune_skipped_current", ref=ref)
                continue

            try:
                snapshot_date = self._parse_snapshot_datetime(ref)
            except (IndexError, ValueError) as exc:
                retained_count += 1
                logger.warning("snapshot_timestamp_parse_failed", ref=ref, error=str(exc))
                continue

            if snapshot_date >= cutoff:
                retained_count += 1
                continue

            try:
                returncode, _, stderr_text = await self._run_git_async(
                    ["git", "-C", repo_path, "branch", "-D", ref],
                    repo_path=repo_path,
                    deadline=deadline,
                    timeout_code="prune_timeout",
                )
            except GitCapabilityError as exc:
                if exc.code == "prune_timeout":
                    retained_count += 1
                    logger.warning("snapshot_prune_timeout", ref=ref)
                    continue
                retained_count += 1
                logger.warning("snapshot_prune_failed", ref=ref, error=exc.message)
                continue

            if returncode == 0:
                pruned_refs.append(ref)
                logger.info("snapshot_pruned", repo_path=repo_path, ref=ref)
            else:
                retained_count += 1
                logger.warning(
                    "snapshot_prune_failed",
                    ref=ref,
                    stderr=stderr_text,
                )

        result = {
            "pruned_count": len(pruned_refs),
            "pruned_refs": pruned_refs,
            "retained_count": retained_count,
        }
        logger.info(
            "snapshots_pruned",
            repo_path=repo_path,
            retention_days=retention_days,
            pruned_count=result["pruned_count"],
            retained_count=result["retained_count"],
        )
        return result

    def _parse_snapshot_datetime(self, snapshot_ref: str) -> datetime:
        parts = snapshot_ref.split("snapshot/edit-")[1]
        timestamp_parts = parts.split("-")
        if len(timestamp_parts) < 4:
            raise ValueError("invalid snapshot timestamp format")
        date_text = (
            f"{timestamp_parts[0]}-"
            f"{timestamp_parts[1]}-"
            f"{timestamp_parts[2]}-"
            f"{timestamp_parts[3]}"
        )
        parsed = datetime.strptime(date_text, "%Y-%m-%d-%H%M")
        return parsed.replace(tzinfo=timezone.utc)

    async def _run_git_async(
        self,
        cmd: list[str],
        repo_path: str,
        deadline: datetime,
        timeout_code: str,
    ) -> tuple[int, str, str]:
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            raise GitCapabilityError(
                code=timeout_code,
                message="Git prune operation timed out",
                details={"repo_path": repo_path, "command": cmd},
                retryable=True,
            )
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
            stdout_b, stderr_b = await asyncio.wait_for(
                process.communicate(),
                timeout=remaining,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise GitCapabilityError(
                code=timeout_code,
                message="Git prune operation timed out",
                details={"repo_path": repo_path, "command": cmd},
                retryable=True,
            ) from exc

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace").strip()
        return process.returncode, stdout, stderr

    async def _list_snapshots_for_prune(
        self,
        repo_path: str,
        deadline: datetime,
    ) -> list[dict[str, Any]]:
        returncode, stdout, stderr = await self._run_git_async(
            ["git", "-C", repo_path, "branch", "--list", "snapshot/*"],
            repo_path=repo_path,
            deadline=deadline,
            timeout_code="prune_timeout",
        )
        if returncode != 0:
            raise GitCapabilityError(
                code="prune_failed",
                message="Failed to list snapshot branches for pruning",
                details={"repo_path": repo_path, "stderr": stderr},
                retryable=False,
            )
        if not stdout.strip():
            return []

        snapshots: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            branch_name = line.strip()
            if not branch_name:
                continue
            try:
                dt = self._parse_snapshot_datetime(branch_name)
                formatted = dt.strftime("%b %d, %Y %H:%M UTC")
                snapshots.append({"ref": branch_name, "timestamp": formatted})
            except (IndexError, ValueError) as exc:
                logger.warning(
                    "snapshot_name_parse_failed",
                    branch_name=branch_name,
                    error=str(exc),
                )
                snapshots.append({"ref": branch_name, "timestamp": "Unknown"})
        snapshots.sort(
            key=lambda snap: (
                self._parse_snapshot_datetime(snap["ref"])
                if snap["timestamp"] != "Unknown"
                else datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True,
        )
        return snapshots

    async def rollback_to_snapshot(
        self,
        repo_path: str,
        snapshot_ref: str,
        operation_id: str,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        """
        Restore files from a snapshot branch without rewriting history.

        Uses git checkout <snapshot_ref> -- . to restore files, then creates
        a new commit showing the rollback operation. This preserves history.

        Args:
            repo_path: Absolute path to git repository root
            snapshot_ref: Snapshot branch name (e.g., "snapshot/edit-2026-02-27-1430")
            operation_id: UUID tracking ID for commit message
            timeout_seconds: Maximum time for git operations (default: 30s per NFR-007)

        Returns:
            {"snapshot_ref": str, "commit_hash": str, "files_restored": int}

        Raises:
            GitCapabilityError: snapshot_not_found, rollback_failed, commit_failed, snapshot_timeout
        """
        # Step 1: Verify snapshot exists
        verify_cmd = ["git", "-C", repo_path, "rev-parse", "--verify", snapshot_ref]

        try:
            process = await asyncio.create_subprocess_exec(
                *verify_cmd,
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
                message=f"Git rollback operation timed out after {timeout_seconds}s",
                details={"repo_path": repo_path, "snapshot_ref": snapshot_ref},
                retryable=True,
            ) from exc

        if process.returncode != 0:
            raise GitCapabilityError(
                code="snapshot_not_found",
                message=f"Snapshot branch not found: {snapshot_ref}",
                details={
                    "repo_path": repo_path,
                    "snapshot_ref": snapshot_ref,
                    "stderr": stderr.decode("utf-8", errors="replace").strip(),
                },
                retryable=False,
            )

        # Step 2: Restore files from snapshot
        checkout_cmd = ["git", "-C", repo_path, "checkout", snapshot_ref, "--", "."]

        process = await asyncio.create_subprocess_exec(
            *checkout_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise GitCapabilityError(
                code="snapshot_timeout",
                message=f"Git checkout timed out after {timeout_seconds}s",
                details={"repo_path": repo_path, "snapshot_ref": snapshot_ref},
                retryable=True,
            ) from exc

        if process.returncode != 0:
            raise GitCapabilityError(
                code="rollback_failed",
                message="Failed to restore files from snapshot",
                details={
                    "repo_path": repo_path,
                    "snapshot_ref": snapshot_ref,
                    "stderr": stderr.decode("utf-8", errors="replace").strip(),
                },
                retryable=False,
            )

        # Step 3: Create commit
        commit_message = f"Rollback to snapshot: {snapshot_ref} (operation: {operation_id[:8]})"
        commit_cmd = ["git", "-C", repo_path, "commit", "-a", "-m", commit_message]

        process = await asyncio.create_subprocess_exec(
            *commit_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise GitCapabilityError(
                code="snapshot_timeout",
                message=f"Git commit timed out after {timeout_seconds}s",
                details={"repo_path": repo_path, "snapshot_ref": snapshot_ref},
                retryable=True,
            ) from exc

        # Handle "nothing to commit" case gracefully
        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            if "nothing to commit" in stderr_text:
                # No changes detected - return current HEAD
                logger.info(
                    "rollback_no_changes",
                    repo_path=repo_path,
                    snapshot_ref=snapshot_ref,
                    message="Rollback produced no changes (already at snapshot state)",
                )
                # Get current HEAD commit
                head_cmd = ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"]
                process = await asyncio.create_subprocess_exec(
                    *head_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(
                    process.communicate(), timeout=timeout_seconds
                )
                commit_hash = stdout.decode("utf-8", errors="replace").strip()

                return {
                    "snapshot_ref": snapshot_ref,
                    "commit_hash": commit_hash,
                    "files_restored": 0,
                }
            else:
                # Real commit failure
                raise GitCapabilityError(
                    code="commit_failed",
                    message="Failed to create rollback commit",
                    details={
                        "repo_path": repo_path,
                        "snapshot_ref": snapshot_ref,
                        "stderr": stderr_text,
                    },
                    retryable=False,
                )

        # Step 4: Get commit hash
        hash_cmd = ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"]
        process = await asyncio.create_subprocess_exec(
            *hash_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds
        )
        commit_hash = stdout.decode("utf-8", errors="replace").strip()

        # Step 5: Count files changed
        diff_cmd = ["git", "-C", repo_path, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"]
        process = await asyncio.create_subprocess_exec(
            *diff_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds
        )
        files_output = stdout.decode("utf-8", errors="replace").strip()
        files_restored = len(files_output.split("\n")) if files_output else 0

        logger.info(
            "rollback_complete",
            repo_path=repo_path,
            snapshot_ref=snapshot_ref,
            commit_hash=commit_hash,
            files_restored=files_restored,
        )

        return {
            "snapshot_ref": snapshot_ref,
            "commit_hash": commit_hash,
            "files_restored": files_restored,
        }
