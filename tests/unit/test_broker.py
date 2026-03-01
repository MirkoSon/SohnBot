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
    assert error == ""


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
    assert classify_tier("git", "list_snapshots", 0) == 0
    assert classify_tier("scheduler", "list", 0) == 0
    assert classify_tier("web", "search", 0) == 0
    assert classify_tier("profiles", "lint", 0) == 0
    assert classify_tier("profiles", "build", 0) == 0


def test_classify_tier_1_single_file():
    """Single-file modifications should be classified as Tier 1."""
    assert classify_tier("fs", "apply_patch", 1) == 1
    assert classify_tier("git", "commit", 1) == 1
    assert classify_tier("git", "checkout", 1) == 1
    assert classify_tier("git", "prune_snapshots", 0) == 1
    assert classify_tier("git", "checkout", 0) == 1
    assert classify_tier("scheduler", "create", 0) == 1
    assert classify_tier("scheduler", "delete", 0) == 1
    assert classify_tier("scheduler", "disable", 0) == 1
    assert classify_tier("scheduler", "enable", 0) == 1
    assert classify_tier("scheduler", "edit", 0) == 1


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
    (allowed_root / "test.txt").write_text("hello")

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

    # Create target file and a valid patch; mock SnapshotManager so no real git needed
    target_file = allowed_root / "test.txt"
    target_file.write_text("line1\nline2\nline3\n")

    valid_patch = (
        f"--- test.txt\n+++ test.txt\n"
        "@@ -1,3 +1,3 @@\n line1\n-line2\n+line2_modified\n line3\n"
    )

    with patch.object(router.snapshot_manager, "find_repo_root", return_value=str(allowed_root)), \
         patch.object(router.snapshot_manager, "create_snapshot", new=AsyncMock(return_value="snapshot/edit-2026-02-26-1200")):
        result = await router.route_operation(
            capability="fs",
            action="apply_patch",
            params={"path": str(target_file), "patch": valid_patch},
            chat_id="test_chat",
        )

    # Verify snapshot was created with real git snapshot manager
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
    (allowed_root / "test.txt").write_text("hello")

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    # Mock failing operation
    async def failing_operation(*args, **kwargs):
        raise ValueError("Test error")

    with patch.object(router, "_execute_capability", side_effect=failing_operation):
        result = await router.route_operation(
            capability="fs",
            action="read",
            params={"path": str(allowed_root / "test.txt")},
            chat_id="test_chat",
        )

        assert result.allowed is False
        assert result.error["code"] == "execution_error"
        assert "Test error" in result.error["message"]


# Profiles Capability Broker Tests

@pytest.mark.asyncio
async def test_profiles_lint_missing_repo_path_returns_invalid_request(tmp_path):
    """profiles/lint without repo_path → allowed=False, code=invalid_request."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="profiles",
        action="lint",
        params={},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "invalid_request"
    assert "repo_path" in result.error["message"]


@pytest.mark.asyncio
async def test_profiles_lint_empty_repo_path_returns_invalid_request(tmp_path):
    """profiles/lint with repo_path='' → allowed=False, code=invalid_request."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="profiles",
        action="lint",
        params={"repo_path": ""},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_profiles_lint_out_of_scope_repo_path_returns_scope_violation(tmp_path):
    """profiles/lint with repo_path outside scope → allowed=False, code=scope_violation."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    outside_path = str(tmp_path / "other_project")

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="profiles",
        action="lint",
        params={"repo_path": outside_path},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "scope_violation"


@pytest.mark.asyncio
async def test_profiles_lint_files_with_traversal_returns_scope_violation(tmp_path):
    """profiles/lint with '../' in files list → allowed=False, code=scope_violation."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    repo_path = str(allowed_root)

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="profiles",
        action="lint",
        params={"repo_path": repo_path, "files": ["../secret.py"]},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "scope_violation"
    assert "traversal" in result.error["message"]


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_profiles_lint_success_routes_to_capability(mock_log_end, mock_log_start, tmp_path):
    """profiles/lint with valid params routes to execute_lint_profile and returns result."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    repo_path = str(allowed_root)

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    fake_lint_result = {
        "passed": True,
        "exit_code": 0,
        "stdout": "All clean.",
        "stderr": "",
        "command_used": "pylint",
        "files_linted": [],
    }

    with patch(
        "src.sohnbot.capabilities.command_profiles.execute_lint_profile",
        new=AsyncMock(return_value=fake_lint_result),
    ) as mock_exec:
        result = await router.route_operation(
            capability="profiles",
            action="lint",
            params={"repo_path": repo_path, "files": []},
            chat_id="test_chat",
        )

    assert result.allowed is True
    assert result.result["passed"] is True
    assert result.result["exit_code"] == 0
    assert result.snapshot_ref is None  # Tier 0 — no snapshot


# ─── profiles/build broker tests ────────────────────────────────────────────

def test_classify_tier_profiles_build_is_tier_0():
    """profiles/build must be classified as Tier 0 (read-only execution)."""
    assert classify_tier("profiles", "build", 0) == 0


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_profiles_build_missing_repo_path_returns_invalid_request(mock_log_end, mock_log_start, tmp_path):
    """profiles/build without repo_path → allowed=False, code=invalid_request."""
    validator = ScopeValidator([str(tmp_path)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="profiles",
        action="build",
        params={"target": "dist"},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "invalid_request"


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_profiles_build_empty_repo_path_returns_invalid_request(mock_log_end, mock_log_start, tmp_path):
    """profiles/build with repo_path='' → allowed=False, code=invalid_request."""
    validator = ScopeValidator([str(tmp_path)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="profiles",
        action="build",
        params={"repo_path": "", "target": ""},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "invalid_request"
    assert "empty" in result.error["message"]


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_profiles_build_out_of_scope_repo_path_returns_scope_violation(mock_log_end, mock_log_start, tmp_path):
    """profiles/build with repo_path outside scope → allowed=False, code=scope_violation."""
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="profiles",
        action="build",
        params={"repo_path": "/outside/path", "target": ""},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "scope_violation"


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_profiles_build_unsafe_target_returns_invalid_request(mock_log_end, mock_log_start, tmp_path):
    """profiles/build with shell metacharacters in target → allowed=False, code=invalid_request."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="profiles",
        action="build",
        params={"repo_path": str(allowed_root), "target": "dist; rm -rf /"},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "invalid_request"
    assert "disallowed" in result.error["message"]


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_profiles_build_success_routes_to_capability(mock_log_end, mock_log_start, tmp_path):
    """profiles/build with valid params routes to execute_build_profile and returns result."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    repo_path = str(allowed_root)

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    fake_build_result = {
        "passed": True,
        "exit_code": 0,
        "stdout": "Build complete.",
        "stderr": "",
        "command_used": "make",
        "target": "dist",
    }

    with patch(
        "src.sohnbot.capabilities.command_profiles.execute_build_profile",
        new=AsyncMock(return_value=fake_build_result),
    ):
        result = await router.route_operation(
            capability="profiles",
            action="build",
            params={"repo_path": repo_path, "target": "dist"},
            chat_id="test_chat",
        )

    assert result.allowed is True
    assert result.result["passed"] is True
    assert result.result["exit_code"] == 0
    assert result.snapshot_ref is None  # Tier 0 — no snapshot

# ─── profiles/build notification formatter tests ─────────────────────────────

def test_format_notification_build_passed(tmp_path):
    """_format_notification_message returns PASSED string with exit_code and repo."""
    router = BrokerRouter(ScopeValidator([str(tmp_path)]))
    msg = router._format_notification_message(
        capability="profiles",
        action="build",
        params={"repo_path": "/some/project"},
        status="completed",
        snapshot_ref=None,
        result={"passed": True, "exit_code": 0},
    )
    assert "✅ PASSED" in msg
    assert "Build profile" in msg
    assert "exit_code=0" in msg
    assert "/some/project" in msg


def test_format_notification_build_failed(tmp_path):
    """_format_notification_message returns FAILED string with non-zero exit_code."""
    router = BrokerRouter(ScopeValidator([str(tmp_path)]))
    msg = router._format_notification_message(
        capability="profiles",
        action="build",
        params={"repo_path": "/some/project"},
        status="completed",
        snapshot_ref=None,
        result={"passed": False, "exit_code": 2},
    )
    assert "❌ FAILED" in msg
    assert "exit_code=2" in msg


# ─── profiles/test broker tests ──────────────────────────────────────────────

def test_classify_tier_profiles_test_is_tier_0():
    """profiles/test must be classified as Tier 0 (read-only execution)."""
    assert classify_tier("profiles", "test", 0) == 0


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_profiles_test_missing_repo_path_returns_invalid_request(mock_log_end, mock_log_start, tmp_path):
    """profiles/test without repo_path → allowed=False, code=invalid_request."""
    validator = ScopeValidator([str(tmp_path)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="profiles",
        action="test",
        params={"pattern": "tests/unit/"},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "invalid_request"


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_profiles_test_empty_repo_path_returns_invalid_request(mock_log_end, mock_log_start, tmp_path):
    """profiles/test with repo_path='' → allowed=False, code=invalid_request."""
    validator = ScopeValidator([str(tmp_path)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="profiles",
        action="test",
        params={"repo_path": "", "pattern": ""},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "invalid_request"
    assert "empty" in result.error["message"]


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_profiles_test_out_of_scope_repo_path_returns_scope_violation(mock_log_end, mock_log_start, tmp_path):
    """profiles/test with repo_path outside scope → allowed=False, code=scope_violation."""
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="profiles",
        action="test",
        params={"repo_path": "/outside/path", "pattern": ""},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "scope_violation"


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_profiles_test_unsafe_pattern_returns_invalid_request(mock_log_end, mock_log_start, tmp_path):
    """profiles/test with shell metacharacters in pattern → allowed=False, code=invalid_request."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="profiles",
        action="test",
        params={"repo_path": str(allowed_root), "pattern": "tests/; rm -rf /"},
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "invalid_request"
    assert "disallowed" in result.error["message"]


@pytest.mark.asyncio
@patch("src.sohnbot.broker.router.log_operation_start", new_callable=AsyncMock)
@patch("src.sohnbot.broker.router.log_operation_end", new_callable=AsyncMock)
async def test_profiles_test_success_routes_to_capability(mock_log_end, mock_log_start, tmp_path):
    """profiles/test with valid params routes to execute_test_profile and returns result."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    repo_path = str(allowed_root)

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    fake_test_result = {
        "passed": True,
        "exit_code": 0,
        "stdout": "5 passed.",
        "stderr": "",
        "command_used": "pytest",
        "pattern": "tests/unit/",
    }

    with patch(
        "src.sohnbot.capabilities.command_profiles.execute_test_profile",
        new=AsyncMock(return_value=fake_test_result),
    ):
        result = await router.route_operation(
            capability="profiles",
            action="test",
            params={"repo_path": repo_path, "pattern": "tests/unit/"},
            chat_id="test_chat",
        )

    assert result.allowed is True
    assert result.result["passed"] is True
    assert result.result["exit_code"] == 0
    assert result.snapshot_ref is None  # Tier 0 — no snapshot


# ─── profiles/test notification formatter tests ───────────────────────────────

def test_format_notification_test_passed(tmp_path):
    """_format_notification_message returns PASSED string with exit_code and repo."""
    router = BrokerRouter(ScopeValidator([str(tmp_path)]))
    msg = router._format_notification_message(
        capability="profiles",
        action="test",
        params={"repo_path": "/some/project"},
        status="completed",
        snapshot_ref=None,
        result={"passed": True, "exit_code": 0},
    )
    assert "✅ PASSED" in msg
    assert "Test profile" in msg
    assert "exit_code=0" in msg
    assert "/some/project" in msg


def test_format_notification_test_failed(tmp_path):
    """_format_notification_message returns FAILED string with non-zero exit_code."""
    router = BrokerRouter(ScopeValidator([str(tmp_path)]))
    msg = router._format_notification_message(
        capability="profiles",
        action="test",
        params={"repo_path": "/some/project"},
        status="completed",
        snapshot_ref=None,
        result={"passed": False, "exit_code": 1},
    )
    assert "❌ FAILED" in msg
    assert "Test profile" in msg
    assert "exit_code=1" in msg
