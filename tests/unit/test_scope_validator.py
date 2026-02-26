"""
Unit tests for ScopeValidator.

Tests path normalization and traversal prevention.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from src.sohnbot.broker.scope_validator import ScopeValidator


class TestScopeValidator:
    """Test path normalization and traversal prevention."""

    @pytest.fixture
    def temp_roots(self, tmp_path):
        """Create temporary test roots."""
        projects = tmp_path / "Projects"
        notes = tmp_path / "Notes"
        projects.mkdir()
        notes.mkdir()
        return [str(projects), str(notes)]

    @pytest.fixture
    def validator(self, temp_roots):
        """Create validator with temp roots."""
        return ScopeValidator(allowed_roots=temp_roots)

    # Path Normalization Tests

    def test_tilde_expansion_within_scope(self):
        """~ expands to user home - paths within scope allowed."""
        # Use actual home directory for this test
        home = Path.home()
        projects = home / "Projects"
        validator = ScopeValidator(allowed_roots=["~/Projects"])

        # Test path within ~/Projects
        test_path = "~/Projects/file.txt"
        is_valid, error_msg = validator.validate_path(test_path)

        assert is_valid is True
        assert error_msg == ""

    def test_tilde_traversal_outside_scope_blocked(self):
        """~/../ traversal attempts rejected."""
        home = Path.home()
        projects = home / "Projects"
        validator = ScopeValidator(allowed_roots=["~/Projects"])

        # Test path that uses ~ but traverses outside
        test_path = "~/Projects/../../etc/passwd"
        is_valid, error_msg = validator.validate_path(test_path)

        assert is_valid is False
        assert "outside allowed scope" in error_msg.lower()

    def test_nonexistent_path_allowed_within_scope(self, validator, temp_roots):
        """Paths that don't exist yet are allowed if within scope."""
        test_path = str(Path(temp_roots[0]) / "new_file.txt")
        is_valid, error_msg = validator.validate_path(test_path)

        assert is_valid is True
        assert error_msg == ""

    def test_relative_path_normalized(self, validator, temp_roots):
        """Relative paths resolved to absolute before validation."""
        # Create a file in allowed root
        test_file = Path(temp_roots[0]) / "test.txt"
        test_file.touch()

        # Change to Projects directory and use relative path
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_roots[0])
            is_valid, error_msg = validator.validate_path("./test.txt")

            assert is_valid is True
            assert error_msg == ""
        finally:
            os.chdir(original_cwd)

    # Traversal Prevention Tests

    def test_parent_directory_traversal_blocked(self, validator, temp_roots):
        """../ traversal attempts rejected."""
        # Try to traverse outside scope using ../
        base_path = Path(temp_roots[0])
        test_path = str(base_path / ".." / ".." / "etc" / "passwd")

        is_valid, error_msg = validator.validate_path(test_path)

        assert is_valid is False
        assert "outside allowed scope" in error_msg.lower()

    def test_absolute_path_outside_scope_blocked(self, validator):
        """Absolute paths outside scope rejected."""
        # Try direct absolute path to /etc/passwd
        is_valid, error_msg = validator.validate_path("/etc/passwd")

        assert is_valid is False
        assert "outside allowed scope" in error_msg.lower()

    def test_absolute_path_on_windows_outside_scope_blocked(self, validator):
        """Windows absolute paths outside scope rejected."""
        # Try Windows system path
        is_valid, error_msg = validator.validate_path("C:\\Windows\\System32\\config\\SAM")

        assert is_valid is False
        assert "outside allowed scope" in error_msg.lower()

    def test_symlink_to_outside_scope_blocked(self, validator, temp_roots, tmp_path):
        """Symlinks pointing outside scope rejected."""
        # Create a symlink in allowed root pointing outside
        link_path = Path(temp_roots[0]) / "malicious_link"
        target_path = tmp_path / "outside_scope" / "secret.txt"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.touch()

        try:
            link_path.symlink_to(target_path)

            is_valid, error_msg = validator.validate_path(str(link_path))

            assert is_valid is False
            assert "outside allowed scope" in error_msg.lower()
        except OSError:
            # Symlink creation might fail on Windows without admin
            pytest.skip("Symlink creation requires admin privileges on Windows")

    # Valid Path Tests

    def test_allowed_root_path_valid(self, validator, temp_roots):
        """Paths within allowed roots pass."""
        is_valid, error_msg = validator.validate_path(temp_roots[0])

        assert is_valid is True
        assert error_msg == ""

    def test_subdirectory_in_allowed_root_valid(self, validator, temp_roots):
        """Subdirectories within scope pass."""
        subdir = Path(temp_roots[0]) / "subdir" / "nested"
        test_path = str(subdir / "file.txt")

        is_valid, error_msg = validator.validate_path(test_path)

        assert is_valid is True
        assert error_msg == ""

    def test_multiple_allowed_roots(self, temp_roots):
        """Multiple roots - paths in any root are valid."""
        validator = ScopeValidator(allowed_roots=temp_roots)

        # Test first root
        is_valid1, _ = validator.validate_path(str(Path(temp_roots[0]) / "file.txt"))
        assert is_valid1 is True

        # Test second root
        is_valid2, _ = validator.validate_path(str(Path(temp_roots[1]) / "note.txt"))
        assert is_valid2 is True

    # Edge Cases

    def test_empty_path_rejected(self, validator):
        """Empty path string rejected."""
        is_valid, error_msg = validator.validate_path("")

        assert is_valid is False
        assert len(error_msg) > 0

    def test_current_directory_dot_within_scope(self, validator, temp_roots):
        """Current directory reference ./ resolved correctly."""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_roots[0])
            is_valid, error_msg = validator.validate_path("./file.txt")

            assert is_valid is True
            assert error_msg == ""
        finally:
            os.chdir(original_cwd)

    def test_mixed_separators_normalized(self, validator, temp_roots):
        """Mixed path separators (/ and \\) normalized."""
        # Use mixed separators
        mixed_path = temp_roots[0].replace("/", "\\") + "/subdir\\file.txt"
        is_valid, error_msg = validator.validate_path(mixed_path)

        assert is_valid is True
        assert error_msg == ""

    # Security-Critical Test Coverage (NFR-010)

    @pytest.mark.parametrize("malicious_path", [
        "../../etc/passwd",
        "../../../root/.ssh/id_rsa",
        "~/../../etc/shadow",
        "/etc/passwd",
        "C:\\Windows\\System32\\config\\SAM",
        "/root/.bashrc",
        "../../../etc/hosts",
    ])
    def test_100_percent_traversal_blocking(self, validator, malicious_path):
        """Verify ALL path traversal techniques blocked (NFR-010)."""
        is_valid, error_msg = validator.validate_path(malicious_path)

        assert is_valid is False, f"Malicious path {malicious_path} was not blocked!"
        assert "outside allowed scope" in error_msg.lower()
