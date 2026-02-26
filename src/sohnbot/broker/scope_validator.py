"""Path validation against configured scope roots."""

import os
from pathlib import Path
from typing import Any, List


class ScopeValidator:
    """Validates file paths against configured scope roots."""

    def __init__(self, allowed_roots: List[str]):
        """
        Initialize scope validator.

        Args:
            allowed_roots: List of allowed root directories (e.g., ["~/Projects", "~/Notes"])
        """
        # Normalize and resolve scope roots (expand ~, resolve symlinks)
        self.allowed_roots = [self._normalize_path(root) for root in allowed_roots]

    def _normalize_path(self, path: str) -> Path:
        """Normalize path separators, expand user home, and resolve safely."""
        normalized = path.replace("\\", "/")
        expanded = os.path.expanduser(normalized)
        return Path(expanded).resolve(strict=False)

    def _coerce_to_path_string(self, path: Any) -> str:
        """Convert supported path input to string."""
        if isinstance(path, Path):
            return str(path)
        if isinstance(path, str):
            return path
        raise TypeError(f"Unsupported path type: {type(path).__name__}")

    def get_allowed_roots(self) -> list[str]:
        """Return normalized allowed roots as strings."""
        return [str(root) for root in self.allowed_roots]

    def get_normalized_path(self, path: Any) -> str | None:
        """
        Return normalized path string when possible, otherwise None.

        This is used for structured broker error details/logging.
        """
        try:
            path_str = self._coerce_to_path_string(path)
            if not path_str:
                return None
            return str(self._normalize_path(path_str))
        except (TypeError, ValueError, RuntimeError):
            return None

    def validate_path(self, path: Any) -> tuple[bool, str]:
        """
        Validate that path is within allowed scope roots.

        Prevents path traversal attacks by:
        - Normalizing paths (resolving .., ~, symlinks)
        - Checking if path starts with an allowed root

        Args:
            path: File path to validate

        Returns:
            Tuple of (is_valid, error_message)
            - is_valid: True if path is within allowed scope
            - error_message: Error message if invalid, None if valid
        """
        # Normalize path (resolve .., ~, symlinks)
        try:
            path_str = self._coerce_to_path_string(path)
        except TypeError:
            return False, "Path outside allowed scope: invalid path type"

        if not path_str:
            return False, "Path outside allowed scope: empty path"

        try:
            normalized = self._normalize_path(path_str)
        except (ValueError, RuntimeError) as e:
            return False, f"Invalid path: {e}"

        # Check if normalized path starts with any allowed root
        for root in self.allowed_roots:
            try:
                normalized.relative_to(root)
                return True, ""  # Path is within allowed scope
            except ValueError:
                continue  # Try next root

        # Path not within any allowed root
        return False, f"Path outside allowed scope: {path_str}"
