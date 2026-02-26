"""Unit tests for broker layer (scope validation, classification, routing)."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.sohnbot.broker.scope_validator import ScopeValidator
from src.sohnbot.broker.operation_classifier import classify_tier
from src.sohnbot.broker.router import BrokerRouter, BrokerResult


# Scope Validation Tests

def test_validate_path_within_scope(tmp_path):
    """Valid paths within scope should be accepted."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    validator = ScopeValidator([str(allowed_root)])

    test_file = allowed_root / "test.txt"
    is_valid, error = validator.validate_path(str(test_file))

    assert is_valid is True
    assert error is None


def test_validate_path_outside_scope(tmp_path):
    """Paths outside scope should be rejected."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    outside_path = tmp_path / "other" / "file.txt"

    validator = ScopeValidator([str(allowed_root)])

    is_valid, error = validator.validate_path(str(outside_path))

    assert is_valid is False
    assert "outside allowed scope" in error


def test_validate_path_traversal_attack(tmp_path):
    """Path traversal attempts (../) should be prevented."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    # Try to escape scope using ../
    attack_path = str(allowed_root / ".." / ".." / "etc" / "passwd")

    validator = ScopeValidator([str(allowed_root)])

    is_valid, error = validator.validate_path(attack_path)

    assert is_valid is False


def test_validate_path_tilde_expansion(tmp_path):
    """~/ should be expanded correctly."""
    # Use actual home directory for tilde test
    validator = ScopeValidator(["~/Projects"])

    # Tilde should be expanded to home directory
    assert len(validator.allowed_roots) == 1
    assert "~" not in str(validator.allowed_roots[0])
    assert validator.allowed_roots[0].is_absolute()


def test_validate_path_relative_to_absolute(tmp_path):
    """Relative paths should be normalized to absolute and checked against scope."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    validator = ScopeValidator([str(allowed_root)])

    # Use relative path (should be normalized to CWD, which is NOT in allowed_root)
    relative_path = "file.txt"

    is_valid, error = validator.validate_path(relative_path)

    # Relative path resolves to CWD, which is outside tmp_path/projects
    assert is_valid is False
    assert "outside allowed scope" in error


# Operation Classification Tests

def test_classify_tier_0_read_operations():
    """Read-only operations should be classified as Tier 0."""
    assert classify_tier("fs", "read", 1) == 0
    assert classify_tier("fs", "list", 0) == 0
    assert classify_tier("fs", "search", 0) == 0
    assert classify_tier("git", "status", 0) == 0
    assert classify_tier("git", "diff", 0) == 0
    assert classify_tier("web", "search", 0) == 0
    assert classify_tier("profiles", "lint", 0) == 0


def test_classify_tier_1_single_file():
    """Single-file modifications should be classified as Tier 1."""
    assert classify_tier("fs", "apply_patch", 1) == 1
    assert classify_tier("git", "commit", 1) == 1
    assert classify_tier("git", "checkout", 1) == 1


def test_classify_tier_2_multi_file():
    """Multi-file modifications should be classified as Tier 2."""
    assert classify_tier("fs", "apply_patch", 2) == 2
    assert classify_tier("fs", "apply_patch", 5) == 2


def test_classify_tier_default_conservative():
    """Unknown operations should default to Tier 2 (conservative)."""
    assert classify_tier("unknown", "unknown", 0) == 2


# Broker Routing Tests

@pytest.mark.asyncio
async def test_route_operation_scope_validation(tmp_path):
    """Scope should be checked before execution."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    # Try to access file outside scope
    outside_path = str(tmp_path / "other" / "file.txt")

    result = await router.route_operation(
        capability="fs",
        action="read",
        params={"path": outside_path},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "scope_violation"


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
async def test_route_operation_logs_start(mock_log_start, tmp_path):
    """Operation start should be logged."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    # Mock database
    with patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock):
        await router.route_operation(
            capability="fs",
            action="read",
            params={"path": str(allowed_root / "test.txt")},
            chat_id="test_chat",
        )

    # Verify log_operation_start was called
    mock_log_start.assert_called_once()
    call_args = mock_log_start.call_args[1]
    assert call_args["capability"] == "fs"
    assert call_args["action"] == "read"
    assert call_args["chat_id"] == "test_chat"
    assert call_args["tier"] == 0  # read is Tier 0


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_route_operation_logs_end(mock_log_end, mock_log_start, tmp_path):
    """Operation end should be logged with duration."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    await router.route_operation(
        capability="fs",
        action="read",
        params={"path": str(allowed_root / "test.txt")},
        chat_id="test_chat",
    )

    # Verify log_operation_end was called
    mock_log_end.assert_called_once()
    call_args = mock_log_end.call_args[1]
    assert call_args["status"] == "completed"
    assert "duration_ms" in call_args


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_route_operation_snapshot_creation_tier_1(mock_log_end, mock_log_start, tmp_path):
    """Tier 1 operations should create snapshot."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="fs",
        action="apply_patch",
        params={"path": str(allowed_root / "test.txt")},  # Single file = Tier 1
        chat_id="test_chat",
    )

    # Verify snapshot was created (placeholder)
    assert result.snapshot_ref is not None
    assert result.snapshot_ref.startswith("snapshot/edit-")


@pytest.mark.asyncio
@pytest.mark.skip(reason="Timeout mocking is complex; timeout logic verified in integration tests")
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_route_operation_timeout_enforcement(mock_log_end, mock_log_start, tmp_path):
    """Operations should timeout after configured seconds (tested in integration)."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    # Mock slow operation
    async def slow_operation(*args, **kwargs):
        import asyncio
        await asyncio.sleep(0.1)

    with patch.object(router, "_execute_capability_placeholder", side_effect=slow_operation):
        # Set very short timeout for test
        import asyncio

        original_timeout = asyncio.timeout

        async def short_timeout(seconds):
            return original_timeout(0.01)  # Very short timeout

        with patch("asyncio.timeout", side_effect=short_timeout):
            result = await router.route_operation(
                capability="fs",
                action="read",
                params={"path": str(allowed_root / "test.txt")},
                chat_id="test_chat",
            )

            assert result.allowed is False
            assert result.error["code"] == "timeout"


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_route_operation_error_handling(mock_log_end, mock_log_start, tmp_path):
    """Exceptions should be logged and returned in BrokerResult."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    # Mock failing operation
    async def failing_operation(*args, **kwargs):
        raise ValueError("Test error")

    with patch.object(router, "_execute_capability_placeholder", side_effect=failing_operation):
        result = await router.route_operation(
            capability="fs",
            action="read",
            params={"path": str(allowed_root / "test.txt")},
            chat_id="test_chat",
        )

        assert result.allowed is False
        assert result.error["code"] == "execution_error"
        assert "Test error" in result.error["message"]
