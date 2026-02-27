"""
Integration tests for scope enforcement.

Tests that broker properly enforces scope validation before
routing file operations to capabilities.
"""

from unittest.mock import patch

import pytest
from pathlib import Path

from src.sohnbot.broker.router import BrokerRouter
from src.sohnbot.broker.scope_validator import ScopeValidator
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager
from scripts.migrate import apply_migrations


class TestBrokerScopeEnforcement:
    """Test broker rejects scope violations."""

    @pytest.fixture
    async def setup_database(self, tmp_path):
        """Set up test database with required schema for broker audit logging."""
        db_path = tmp_path / "test.db"
        migrations_dir = (
            Path(__file__).parent.parent.parent
            / "src"
            / "sohnbot"
            / "persistence"
            / "migrations"
        )

        apply_migrations(db_path, migrations_dir)
        db_manager = DatabaseManager(db_path)
        set_db_manager(db_manager)

        yield db_manager

        await db_manager.close()

    @pytest.fixture
    def temp_allowed_root(self, tmp_path):
        """Create temporary allowed root directory."""
        projects = tmp_path / "Projects"
        projects.mkdir()
        return str(projects)

    @pytest.fixture
    def scope_validator(self, temp_allowed_root):
        """Create ScopeValidator with temp root."""
        return ScopeValidator(allowed_roots=[temp_allowed_root])

    @pytest.fixture
    def broker(self, scope_validator):
        """Create BrokerRouter with scope validator."""
        return BrokerRouter(scope_validator=scope_validator)

    # Broker Blocking Tests

    @pytest.mark.asyncio
    async def test_broker_blocks_traversal_attempt(self, broker, temp_allowed_root):
        """Broker returns allowed=False for ../../../etc/passwd."""
        # Try path traversal attack
        malicious_path = str(Path(temp_allowed_root) / ".." / ".." / ".." / "etc" / "passwd")

        result = await broker.route_operation(
            capability="fs",
            action="read",
            params={"path": malicious_path},
            chat_id="test_user"
        )

        assert result.allowed is False
        assert result.error is not None
        assert result.error["code"] == "scope_violation"
        assert "outside allowed scope" in result.error["message"].lower()
        assert result.error["retryable"] is False

    @pytest.mark.asyncio
    async def test_broker_blocks_absolute_path_outside_scope(self, broker):
        """Broker blocks absolute paths outside configured scope."""
        result = await broker.route_operation(
            capability="fs",
            action="read",
            params={"path": "/etc/passwd"},
            chat_id="test_user"
        )

        assert result.allowed is False
        assert result.error["code"] == "scope_violation"
        assert result.error["details"]["path"] == "/etc/passwd"
        assert result.error["details"]["normalized_path"] == "/etc/passwd"
        assert isinstance(result.error["details"]["allowed_roots"], list)
        assert len(result.error["details"]["allowed_roots"]) >= 1

    @pytest.mark.asyncio
    async def test_broker_scope_validation_passes_for_valid_path(self, scope_validator, temp_allowed_root):
        """Scope validator allows paths within configured scope."""
        valid_path = str(Path(temp_allowed_root) / "file.txt")

        # Test scope validation directly (not full broker routing)
        is_valid, error_msg = scope_validator.validate_path(valid_path)

        assert is_valid is True
        assert error_msg == ""

    @pytest.mark.asyncio
    async def test_broker_validates_multiple_paths(self, broker, temp_allowed_root):
        """Broker validates all paths in params["paths"] list."""
        valid_path = str(Path(temp_allowed_root) / "file1.txt")
        invalid_path = "/etc/passwd"

        # Mix valid and invalid paths
        result = await broker.route_operation(
            capability="fs",
            action="read_multiple",
            params={"paths": [valid_path, invalid_path]},
            chat_id="test_user"
        )

        # Should reject because one path is invalid
        assert result.allowed is False
        assert result.error["code"] == "scope_violation"

    @pytest.mark.asyncio
    async def test_broker_logs_scope_violation(self, broker):
        """Scope violations logged for security auditing."""
        with patch("src.sohnbot.broker.router.logger.warning") as mock_warning:
            await broker.route_operation(
                capability="fs",
                action="read",
                params={"path": "/etc/passwd"},
                chat_id="malicious_user",
            )

            mock_warning.assert_called_once()
            event_name, event_kwargs = mock_warning.call_args.args[0], mock_warning.call_args.kwargs
            assert event_name == "scope_violation_blocked"
            assert event_kwargs["chat_id"] == "malicious_user"
            assert event_kwargs["attempted_path"] == "/etc/passwd"
            assert event_kwargs["normalized_path"] == "/etc/passwd"

    @pytest.mark.asyncio
    async def test_broker_blocks_invalid_path_type_without_crash(self, broker):
        """Invalid path types return scope_violation and clean operation tracking."""
        result = await broker.route_operation(
            capability="fs",
            action="read",
            params={"path": 123},
            chat_id="test_user",
        )

        assert result.allowed is False
        assert result.error["code"] == "scope_violation"
        assert "invalid path type" in result.error["message"].lower()
        assert result.error["details"]["path"] == "123"
        assert result.error["details"]["normalized_path"] is None
        assert result.operation_id not in broker._operation_start_times

    @pytest.mark.asyncio
    async def test_broker_operation_id_cleanup_on_scope_violation(self, broker):
        """Operation ID cleaned up when scope validation fails."""
        # This tests the memory leak prevention mentioned in broker code
        result = await broker.route_operation(
            capability="fs",
            action="read",
            params={"path": "/etc/passwd"},
            chat_id="test_user"
        )

        assert result.allowed is False
        # Operation ID should have been removed from _operation_start_times
        # (prevents memory leak from accumulating rejected operations)
        assert result.operation_id not in broker._operation_start_times

    # Security Test Coverage (NFR-010 Validation)

    @pytest.mark.parametrize("malicious_path", [
        "../../etc/passwd",
        "../../../root/.ssh/id_rsa",
        "~/../../etc/shadow",
        "/etc/passwd",
        "C:\\Windows\\System32\\config\\SAM",
        "/root/.bashrc",
        "../../../etc/hosts",
    ])
    @pytest.mark.asyncio
    async def test_100_percent_traversal_blocking_via_broker(self, broker, malicious_path):
        """Verify ALL path traversal techniques blocked through broker (NFR-010)."""
        result = await broker.route_operation(
            capability="fs",
            action="read",
            params={"path": malicious_path},
            chat_id="attacker"
        )

        assert result.allowed is False, f"Malicious path {malicious_path} was not blocked by broker!"
        assert result.error["code"] == "scope_violation"
        assert result.error["retryable"] is False

    # Non-File Operations (Should NOT trigger scope validation)

    @pytest.mark.asyncio
    async def test_broker_does_not_validate_non_file_operations(self, broker, setup_database):
        """Non-file operations (git, scheduler, etc.) bypass scope validation."""
        # Git operations should not trigger scope validation
        result = await broker.route_operation(
            capability="git",
            action="status",
            params={},
            chat_id="test_user"
        )

        # Should be allowed (capability not implemented, but no scope error)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_broker_validates_only_fs_capability(self, broker, temp_allowed_root, setup_database):
        """Only fs capability triggers scope validation."""
        # Verify git read-only operations bypass scope validation (Tier 0, no snapshot needed)
        result_git = await broker.route_operation(
            capability="git",
            action="status",
            params={},
            chat_id="test_user"
        )
        assert result_git.allowed is True  # No scope check for git

        # Verify fs capability DOES validate paths
        result_fs = await broker.route_operation(
            capability="fs",
            action="read",
            params={"path": "/etc/passwd"},
            chat_id="test_user"
        )
        assert result_fs.allowed is False  # Scope check blocks invalid path
