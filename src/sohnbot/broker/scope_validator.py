"""Path validation against configured scope roots."""

from pathlib import Path
from typing import List


class ScopeValidator:
    """Validates file paths against configured scope roots."""

    def __init__(self, allowed_roots: List[str]):
        """
        Initialize scope validator.

        Args:
            allowed_roots: List of allowed root directories (e.g., ["~/Projects", "~/Notes"])
        """
        # Normalize and resolve scope roots (expand ~, resolve symlinks)
        self.allowed_roots = [
            Path(root).expanduser().resolve() for root in allowed_roots
        ]

    def validate_path(self, path: str) -> tuple[bool, str | None]:
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
            normalized = Path(path).expanduser().resolve()
        except (ValueError, RuntimeError) as e:
            return False, f"Invalid path: {e}"

        # Check if normalized path starts with any allowed root
        for root in self.allowed_roots:
            try:
                normalized.relative_to(root)
                return True, None  # Path is within allowed scope
            except ValueError:
                continue  # Try next root

        # Path not within any allowed root
        return False, f"Path outside allowed scope: {path}"
