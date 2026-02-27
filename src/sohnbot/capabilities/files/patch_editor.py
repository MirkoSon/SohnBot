"""Patch editor capability for applying unified diff patches to files."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

try:
    import patch as patch_lib
except ModuleNotFoundError:  # pragma: no cover - exercised via fallback path
    patch_lib = None
import structlog

from .file_ops import FileCapabilityError

logger = structlog.get_logger(__name__)


class PatchEditor:
    """Applies unified diff patches to in-scope files."""

    def apply_patch(
        self, path: str, patch_content: str, patch_max_size_kb: int = 50
    ) -> dict[str, Any]:
        """
        Apply a unified diff patch to a file.

        Args:
            path: Absolute path to the target file
            patch_content: Unified diff patch content as string
            patch_max_size_kb: Maximum allowed patch size in KB (default 50)

        Returns:
            dict with keys: path, lines_added, lines_removed

        Raises:
            FileCapabilityError: On validation failure or application error
        """
        # 1. Size check
        encoded = patch_content.encode()
        max_bytes = patch_max_size_kb * 1024
        if len(encoded) > max_bytes:
            raise FileCapabilityError(
                code="patch_too_large",
                message=f"Patch exceeds {patch_max_size_kb}KB limit",
                details={
                    "size_bytes": len(encoded),
                    "max_size_bytes": max_bytes,
                },
                retryable=False,
            )

        # 2. Format check — must contain all three unified diff markers
        if not (
            "---" in patch_content
            and "+++" in patch_content
            and "@@" in patch_content
        ):
            raise FileCapabilityError(
                code="invalid_patch_format",
                message="Patch must be valid unified diff format (missing ---, +++, or @@ markers)",
                details={"patch_preview": patch_content[:200]},
                retryable=False,
            )

        # 3. Single-file patch validation: count distinct source file targets
        #    A multi-file patch would silently corrupt the target file because
        #    _normalize_patch_paths replaces ALL --- / +++ headers with the
        #    same filename, causing the patch library to apply foreign hunks.
        source_files = _count_patch_source_files(patch_content)
        if source_files > 1:
            raise FileCapabilityError(
                code="invalid_patch_format",
                message=(
                    f"Patch targets {source_files} files but apply_patch accepts "
                    "only single-file patches"
                ),
                details={"source_file_count": source_files},
                retryable=False,
            )

        if _uses_dev_null_headers(patch_content):
            raise FileCapabilityError(
                code="patch_apply_failed",
                message="Creating or deleting files via /dev/null headers is not supported",
                details={"path": path},
                retryable=False,
            )

        # 4. Target file must exist
        file_path = Path(path)
        if not file_path.exists():
            raise FileCapabilityError(
                code="path_not_found",
                message="Path not found",
                details={"path": str(file_path)},
                retryable=False,
            )

        # 5. Count lines added/removed from diff hunks
        lines_added, lines_removed = _count_diff_lines(patch_content)

        # 6. Normalize patch paths to the target file's name so the library
        #    can resolve the file relative to its parent directory
        normalized = _normalize_patch_paths(patch_content, str(file_path.name))
        root = str(file_path.parent)

        # 7. Apply patch
        if patch_lib is not None:
            try:
                pset = patch_lib.fromstring(normalized.encode())
            except Exception as exc:
                raise FileCapabilityError(
                    code="invalid_patch_format",
                    message=f"Failed to parse patch: {exc}",
                    details={"path": path},
                    retryable=False,
                ) from exc

            if not pset:
                raise FileCapabilityError(
                    code="invalid_patch_format",
                    message="Patch parsed as empty — check format",
                    details={"path": path},
                    retryable=False,
                )

            result = pset.apply(root=root)
            if not result:
                raise FileCapabilityError(
                    code="patch_apply_failed",
                    message="Patch application failed (hunk mismatch or conflict)",
                    details={"path": path},
                    retryable=False,
                )
        else:
            _apply_patch_fallback(file_path=file_path, patch_content=normalized)

        logger.info(
            "patch_applied",
            path=path,
            lines_added=lines_added,
            lines_removed=lines_removed,
        )

        return {
            "path": path,
            "lines_added": lines_added,
            "lines_removed": lines_removed,
        }


def _normalize_patch_paths(patch_content: str, filename: str) -> str:
    """
    Replace --- and +++ path lines with just the target filename.

    This allows the patch library to resolve the file relative to its
    parent directory regardless of how paths appear in the diff header.
    """
    lines: list[str] = []
    for line in patch_content.splitlines(keepends=True):
        if line.startswith("--- ") or line.startswith("+++ "):
            prefix = line[:4]
            rest = line[4:]
            # Preserve optional tab-separated timestamp suffix
            parts = rest.split("\t", 1)
            suffix = "\t" + parts[1] if len(parts) > 1 else "\n"
            lines.append(f"{prefix}{filename}{suffix}")
        else:
            lines.append(line)
    return "".join(lines)


def _count_patch_source_files(patch_content: str) -> int:
    """
    Count the number of distinct source files targeted by the patch.

    Parses `--- <path>` lines (excluding `---` alone or `--- /dev/null`).
    Returns the number of unique source paths found.
    """
    source_paths: set[str] = set()
    for line in patch_content.splitlines():
        if line.startswith("--- "):
            path_part = line[4:].split("\t")[0].strip()
            # Skip /dev/null (new-file patches) and bare "---" section separators
            if path_part and path_part != "/dev/null":
                source_paths.add(path_part)
    return len(source_paths)


def _uses_dev_null_headers(patch_content: str) -> bool:
    """Return True when patch includes new/delete file headers via /dev/null."""
    for line in patch_content.splitlines():
        if line.startswith("--- /dev/null") or line.startswith("+++ /dev/null"):
            return True
    return False


def _count_diff_lines(patch_content: str) -> tuple[int, int]:
    """
    Count added and removed lines in a unified diff.

    Ignores +++ / --- header lines; counts only hunk content lines.
    """
    added = 0
    removed = 0
    for line in patch_content.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _apply_patch_fallback(file_path: Path, patch_content: str) -> None:
    """Apply a single-file unified diff patch without external dependency."""
    original = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    result: list[str] = []
    src_index = 0
    lines = patch_content.splitlines(keepends=True)
    i = 0

    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") or line.startswith("+++ "):
            i += 1
            continue

        hunk_match = _HUNK_RE.match(line.rstrip("\n"))
        if not hunk_match:
            i += 1
            continue

        old_start = int(hunk_match.group(1))
        # Copy untouched segment up to hunk start.
        target_index = max(0, old_start - 1)
        while src_index < target_index and src_index < len(original):
            result.append(original[src_index])
            src_index += 1
        i += 1

        while i < len(lines):
            hunk_line = lines[i]
            if hunk_line.startswith("@@"):
                break
            if hunk_line.startswith("\\"):
                i += 1
                continue

            marker = hunk_line[:1]
            payload = hunk_line[1:]
            if marker == " ":
                if src_index >= len(original) or original[src_index] != payload:
                    raise FileCapabilityError(
                        code="patch_apply_failed",
                        message="Patch application failed (context mismatch)",
                        details={"path": str(file_path)},
                        retryable=False,
                    )
                result.append(payload)
                src_index += 1
            elif marker == "-":
                if src_index >= len(original) or original[src_index] != payload:
                    raise FileCapabilityError(
                        code="patch_apply_failed",
                        message="Patch application failed (remove mismatch)",
                        details={"path": str(file_path)},
                        retryable=False,
                    )
                src_index += 1
            elif marker == "+":
                result.append(payload)
            else:
                raise FileCapabilityError(
                    code="invalid_patch_format",
                    message="Unsupported unified diff line format",
                    details={"line": hunk_line[:200]},
                    retryable=False,
                )
            i += 1

    # Append any remaining untouched source.
    while src_index < len(original):
        result.append(original[src_index])
        src_index += 1

    file_path.write_text("".join(result), encoding="utf-8")
