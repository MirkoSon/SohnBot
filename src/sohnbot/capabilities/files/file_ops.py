"""File capability operations for list/read/search."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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

    def __init__(self, excluded_dirs: set[str] | None = None):
        self.excluded_dirs = excluded_dirs or EXCLUDED_DIRS

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
        for current_root, dirs, filenames in os.walk(root):
            # Prune excluded directories from traversal.
            dirs[:] = [d for d in dirs if d not in self.excluded_dirs]

            current_path = Path(current_root)
            for name in filenames:
                file_path = current_path / name
                stat_result = file_path.stat()
                files.append(
                    {
                        "path": str(file_path),
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
            content = file_path.read_text(encoding="utf-8")
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
            try:
                file_path, line_no, content = line.split(":", 2)
                matches.append(
                    {
                        "path": file_path,
                        "line": int(line_no),
                        "content": content,
                    }
                )
            except ValueError:
                # Ignore malformed output line instead of failing the whole search.
                continue

        return {"matches": matches, "count": len(matches)}
