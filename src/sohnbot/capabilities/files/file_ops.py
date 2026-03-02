"""File capability operations for list/read/search."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...broker.scope_validator import ScopeValidator


EXCLUDED_DIRS = {".git", ".venv", "node_modules"}


@dataclass
class FileCapabilityError(Exception):
    """Structured error for file capability operations."""

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


class FileOps:
    """Implements Tier-0 filesystem operations."""

    def __init__(
        self,
        excluded_dirs: set[str] | None = None,
        scope_validator: "ScopeValidator | None" = None,
    ):
        self.excluded_dirs = excluded_dirs or EXCLUDED_DIRS
        self.scope_validator = scope_validator

    def _revalidate_path(self, path: str | Path) -> Path:
        """
        Re-validate real path at I/O boundary to reduce TOCTOU window.

        This is a best-effort userspace mitigation; kernel-level controls would
        still be needed to eliminate TOCTOU races completely.
        """
        resolved = Path(os.path.realpath(str(path)))
        if self.scope_validator is not None:
            is_valid, error_msg = self.scope_validator.validate_path(str(resolved))
            if not is_valid:
                raise FileCapabilityError(
                    code="scope_violation",
                    message=error_msg or "Path outside allowed scope",
                    details={"path": str(path), "resolved_path": str(resolved)},
                    retryable=False,
                )
        return resolved

    def list_files(self, path: str) -> dict[str, Any]:
        """Recursively list files with metadata, excluding traversal dirs."""
        root = Path(path)
        if not root.exists():
            raise FileCapabilityError(
                code="path_not_found",
                message="Path not found",
                details={"path": str(root)},
                retryable=False,
            )
        if not root.is_dir():
            raise FileCapabilityError(
                code="invalid_directory",
                message="Path must be a directory",
                details={"path": str(root)},
                retryable=False,
            )

        files: list[dict[str, Any]] = []
        stack: list[Path] = [root]
        while stack:
            current_path = self._revalidate_path(stack.pop())
            for entry in current_path.iterdir():
                if entry.is_dir():
                    if entry.name in self.excluded_dirs:
                        continue
                    stack.append(entry)
                    continue

                stat_result = entry.stat()
                files.append(
                    {
                        "path": str(entry),
                        "size": stat_result.st_size,
                        "modified_at": int(stat_result.st_mtime),
                    }
                )

        return {"files": files, "count": len(files)}

    def read_file(self, path: str, max_size_mb: int = 10) -> dict[str, Any]:
        """Read UTF-8 text file contents with binary/size safeguards."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileCapabilityError(
                code="path_not_found",
                message="Path not found",
                details={"path": str(file_path)},
                retryable=False,
            )
        if not file_path.is_file():
            raise FileCapabilityError(
                code="invalid_file",
                message="Path must be a file",
                details={"path": str(file_path)},
                retryable=False,
            )

        stat_result = file_path.stat()
        max_bytes = max_size_mb * 1024 * 1024
        if stat_result.st_size > max_bytes:
            raise FileCapabilityError(
                code="file_too_large",
                message=f"File exceeds {max_size_mb}MB limit",
                details={
                    "path": str(file_path),
                    "size_bytes": stat_result.st_size,
                    "max_size_bytes": max_bytes,
                },
                retryable=False,
            )

        sample = file_path.read_bytes()[:4096]
        if b"\x00" in sample:
            raise FileCapabilityError(
                code="binary_not_supported",
                message="Binary files not supported",
                details={"path": str(file_path)},
                retryable=False,
            )

        try:
            # Re-validate immediately before the text read boundary.
            safe_path = self._revalidate_path(file_path)
            content = safe_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise FileCapabilityError(
                code="binary_not_supported",
                message="Binary files not supported",
                details={"path": str(file_path), "error": str(exc)},
                retryable=False,
            ) from exc

        return {
            "path": str(file_path),
            "size": stat_result.st_size,
            "modified_at": int(stat_result.st_mtime),
            "content": content,
        }

    async def search_files(
        self, path: str, pattern: str, timeout_seconds: int = 5
    ) -> dict[str, Any]:
        """Search files using ripgrep with timeout and traversal exclusions."""
        root = Path(path)
        if not root.exists():
            raise FileCapabilityError(
                code="path_not_found",
                message="Path not found",
                details={"path": str(root)},
                retryable=False,
            )
        if not root.is_dir():
            raise FileCapabilityError(
                code="invalid_directory",
                message="Path must be a directory",
                details={"path": str(root)},
                retryable=False,
            )
        if not pattern:
            raise FileCapabilityError(
                code="invalid_pattern",
                message="Search pattern must not be empty",
                details={"path": str(root)},
                retryable=False,
            )

        cmd = [
            "rg",
            "--line-number",
            "--with-filename",
            "--no-heading",
            "--color",
            "never",
            "--glob",
            "!.git/**",
            "--glob",
            "!.venv/**",
            "--glob",
            "!node_modules/**",
            pattern,
            str(root),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise FileCapabilityError(
                code="rg_not_found",
                message="ripgrep (rg) is required for search operations",
                details={"path": str(root)},
                retryable=False,
            ) from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise FileCapabilityError(
                code="search_timeout",
                message=f"Search timed out after {timeout_seconds}s",
                details={"path": str(root), "pattern": pattern},
                retryable=True,
            ) from exc

        if process.returncode == 1:
            # ripgrep uses 1 for "no matches".
            return {"matches": [], "count": 0}

        if process.returncode != 0:
            raise FileCapabilityError(
                code="search_error",
                message="Search failed",
                details={
                    "path": str(root),
                    "pattern": pattern,
                    "stderr": stderr.decode("utf-8", errors="replace").strip(),
                },
                retryable=False,
            )

        matches: list[dict[str, Any]] = []
        output = stdout.decode("utf-8", errors="replace")
        for line in output.splitlines():
            # Format: path:line_number:content
            # On Windows, paths may contain drive letters (C:\...), so we need to handle colons carefully
            try:
                # Split into at most 3 parts, but account for Windows drive letters
                parts = line.split(":")
                if len(parts) < 3:
                    continue  # Malformed line

                # If first part is a single letter (Windows drive), rejoin it with the second part
                if len(parts[0]) == 1 and parts[0].isalpha():
                    # Windows path: C:\path\file:line:content
                    file_path = parts[0] + ":" + parts[1]
                    line_no = parts[2]
                    content = ":".join(parts[3:]) if len(parts) > 3 else ""
                else:
                    # Unix path: /path/file:line:content
                    file_path = parts[0]
                    line_no = parts[1]
                    content = ":".join(parts[2:])

                matches.append(
                    {
                        "path": file_path,
                        "line": int(line_no),
                        "content": content,
                    }
                )
            except (ValueError, IndexError):
                # Ignore malformed output line instead of failing the whole search.
                continue

        return {"matches": matches, "count": len(matches)}
