"""TOCTOU-focused tests for scope validation symlink handling."""

from pathlib import Path

import pytest

from src.sohnbot.broker.scope_validator import ScopeValidator


def test_symlink_target_outside_scope_is_rejected(tmp_path):
    allowed_root = tmp_path / "allowed"
    outside_root = tmp_path / "outside"
    allowed_root.mkdir()
    outside_root.mkdir()

    target = outside_root / "secret.txt"
    target.write_text("secret")
    link = allowed_root / "secret-link"

    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation requires elevated privileges on this platform")

    validator = ScopeValidator([str(allowed_root)])
    is_valid, error = validator.validate_path(str(link))

    assert is_valid is False
    assert "outside allowed scope" in error.lower()


def test_symlink_chain_resolving_outside_scope_is_rejected(tmp_path):
    allowed_root = tmp_path / "allowed"
    outside_root = tmp_path / "outside"
    allowed_root.mkdir()
    outside_root.mkdir()

    chain_c = outside_root / "chain-c.txt"
    chain_c.write_text("outside")
    chain_b = allowed_root / "chain-b"
    chain_a = allowed_root / "chain-a"

    try:
        chain_b.symlink_to(chain_c)
        chain_a.symlink_to(chain_b)
    except OSError:
        pytest.skip("Symlink creation requires elevated privileges on this platform")

    validator = ScopeValidator([str(allowed_root)])
    is_valid, error = validator.validate_path(str(chain_a))

    assert is_valid is False
    assert "outside allowed scope" in error.lower()


def test_symlink_target_inside_scope_is_accepted(tmp_path):
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()

    target = allowed_root / "safe.txt"
    target.write_text("safe")
    link = allowed_root / "safe-link"

    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation requires elevated privileges on this platform")

    validator = ScopeValidator([str(allowed_root)])
    is_valid, error = validator.validate_path(str(link))

    assert is_valid is True
    assert error == ""


def test_nonexistent_path_within_scope_is_accepted(tmp_path):
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    validator = ScopeValidator([str(allowed_root)])

    candidate = allowed_root / "does-not-exist" / "file.txt"
    is_valid, error = validator.validate_path(str(candidate))

    assert is_valid is True
    assert error == ""
