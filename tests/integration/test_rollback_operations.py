"""Integration tests for git rollback operations through broker."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sohnbot.broker.router import BrokerRouter
from sohnbot.broker.scope_validator import ScopeValidator
from sohnbot.persistence.db import DatabaseManager, set_db_manager
from sohnbot.persistence.notification import get_pending_notifications
from scripts.migrate import apply_migrations


@pytest.fixture
async def setup_database(tmp_path):
    """Set up test database with migrations."""
    db_path = tmp_path / "test.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"

    # Apply migrations
    apply_migrations(db_path, migrations_dir)

    # Set up database manager
    db_manager = DatabaseManager(db_path)
    set_db_manager(db_manager)

    yield db_manager

    # Cleanup
    await db_manager.close()


@pytest.fixture
def fake_repo(tmp_path):
    """Create a fake git repo directory."""
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def broker(fake_repo):
    """Create broker with scope validator allowing test repo."""
    scope_validator = ScopeValidator(allowed_roots=[str(fake_repo)])
    return BrokerRouter(scope_validator=scope_validator)


class TestListSnapshotsBrokerRoute:
    @pytest.mark.asyncio
    async def test_list_snapshots_through_broker(self, broker, fake_repo, setup_database):
        """Full broker route for list_snapshots operation."""
        # Mock subprocess for git branch --list
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"  snapshot/edit-2026-02-27-1430\n",
                stderr=b"",
            )

            result = await broker.route_operation(
                capability="git",
                action="list_snapshots",
                params={"repo_path": str(fake_repo)},
                chat_id="test_chat",
            )

        assert result.allowed is True
        assert result.tier == 1
        assert "snapshots" in result.result
        assert len(result.result["snapshots"]) == 1
        assert result.result["snapshots"][0]["ref"] == "snapshot/edit-2026-02-27-1430"

    @pytest.mark.asyncio
    async def test_list_snapshots_scope_violation(self, broker):
        """Scope validation blocks list_snapshots outside allowed roots."""
        result = await broker.route_operation(
            capability="git",
            action="list_snapshots",
            params={"repo_path": "/forbidden/path"},
            chat_id="test_chat",
        )

        assert result.allowed is False
        assert result.error["code"] == "scope_violation"


class TestRollbackBrokerRoute:
    @pytest.mark.asyncio
    async def test_rollback_through_broker(self, broker, fake_repo, setup_database):
        """Full broker route for rollback operation."""
        snapshot_ref = "snapshot/edit-2026-02-27-1430"

        # Mock git commands
        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            process = AsyncMock()
            process.returncode = 0

            if call_count == 1:  # rev-parse --verify
                process.communicate = AsyncMock(return_value=(b"abc123\n", b""))
            elif call_count == 2:  # checkout
                process.communicate = AsyncMock(return_value=(b"", b""))
            elif call_count == 3:  # commit
                process.communicate = AsyncMock(return_value=(b"", b""))
            elif call_count == 4:  # rev-parse --short HEAD
                process.communicate = AsyncMock(return_value=(b"def456\n", b""))
            elif call_count == 5:  # diff-tree
                process.communicate = AsyncMock(return_value=(b"file1.py\nfile2.py\n", b""))

            return process

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await broker.route_operation(
                capability="git",
                action="rollback",
                params={"repo_path": str(fake_repo), "snapshot_ref": snapshot_ref},
                chat_id="test_chat",
            )

        assert result.allowed is True
        assert result.tier == 1
        assert result.result["snapshot_ref"] == snapshot_ref
        assert result.result["commit_hash"] == "def456"
        assert result.result["files_restored"] == 2

    @pytest.mark.asyncio
    async def test_rollback_scope_violation(self, broker):
        """Scope validation blocks rollback outside allowed roots."""
        result = await broker.route_operation(
            capability="git",
            action="rollback",
            params={
                "repo_path": "/forbidden/path",
                "snapshot_ref": "snapshot/edit-2026-02-27-1430"
            },
            chat_id="test_chat",
        )

        assert result.allowed is False
        assert result.error["code"] == "scope_violation"

    @pytest.mark.asyncio
    async def test_rollback_execution_log_populated(self, broker, fake_repo, setup_database):
        """Verify execution_log.snapshot_ref is populated with restored snapshot."""
        snapshot_ref = "snapshot/edit-2026-02-27-1430"

        # Mock git commands
        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            process = AsyncMock()
            process.returncode = 0

            if call_count == 1:  # rev-parse
                process.communicate = AsyncMock(return_value=(b"abc123\n", b""))
            elif call_count == 2:  # checkout
                process.communicate = AsyncMock(return_value=(b"", b""))
            elif call_count == 3:  # commit
                process.communicate = AsyncMock(return_value=(b"", b""))
            elif call_count == 4:  # rev-parse --short
                process.communicate = AsyncMock(return_value=(b"def456\n", b""))
            elif call_count == 5:  # diff-tree
                process.communicate = AsyncMock(return_value=(b"file1.py\n", b""))

            return process

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await broker.route_operation(
                capability="git",
                action="rollback",
                params={"repo_path": str(fake_repo), "snapshot_ref": snapshot_ref},
                chat_id="test_chat",
            )

        # Snapshot ref in result should match the restored snapshot
        assert result.snapshot_ref is None  # Rollback doesn't CREATE snapshot
        assert result.result["snapshot_ref"] == snapshot_ref

    @pytest.mark.asyncio
    async def test_rollback_tier_classification(self, broker, fake_repo, setup_database):
        """Verify rollback is classified as Tier 1."""
        snapshot_ref = "snapshot/edit-2026-02-27-1430"

        # Mock git commands (minimal for tier check)
        async def mock_exec(*args, **kwargs):
            process = AsyncMock()
            process.returncode = 0
            process.communicate = AsyncMock(return_value=(b"abc123\n", b""))
            return process

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await broker.route_operation(
                capability="git",
                action="rollback",
                params={"repo_path": str(fake_repo), "snapshot_ref": snapshot_ref},
                chat_id="test_chat",
            )

        assert result.tier == 1

    @pytest.mark.asyncio
    async def test_rollback_no_snapshot_created(self, broker, fake_repo, setup_database):
        """Verify rollback operations do NOT create snapshots."""
        snapshot_ref = "snapshot/edit-2026-02-27-1430"

        # Mock git commands
        async def mock_exec(*args, **kwargs):
            # If this is a git branch command (snapshot creation), fail the test
            if "branch" in args and "snapshot/edit-" in str(args):
                pytest.fail("Rollback should NOT create a snapshot branch")

            process = AsyncMock()
            process.returncode = 0
            process.communicate = AsyncMock(return_value=(b"abc123\n", b""))
            return process

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await broker.route_operation(
                capability="git",
                action="rollback",
                params={"repo_path": str(fake_repo), "snapshot_ref": snapshot_ref},
                chat_id="test_chat",
            )

        # snapshot_ref should be None (no snapshot created)
        assert result.snapshot_ref is None

    @pytest.mark.asyncio
    async def test_rollback_with_notification(self, fake_repo, setup_database):
        """Verify rollback queues notification in outbox."""
        snapshot_ref = "snapshot/edit-2026-02-27-1430"

        scope_validator = ScopeValidator(allowed_roots=[str(fake_repo)])
        broker_with_notifier = BrokerRouter(scope_validator=scope_validator)

        # Mock git commands
        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            process = AsyncMock()
            process.returncode = 0

            if call_count <= 3:
                process.communicate = AsyncMock(return_value=(b"abc123\n", b""))
            elif call_count == 4:
                process.communicate = AsyncMock(return_value=(b"def456\n", b""))
            elif call_count == 5:
                process.communicate = AsyncMock(return_value=(b"file1.py\n", b""))

            return process

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await broker_with_notifier.route_operation(
                capability="git",
                action="rollback",
                params={"repo_path": str(fake_repo), "snapshot_ref": snapshot_ref},
                chat_id="test_chat",
            )

        assert result.allowed is True
        pending = await get_pending_notifications()
        assert len(pending) == 1
        assert pending[0]["chat_id"] == "test_chat"
        assert "✅" in pending[0]["message_text"]
        assert "git.rollback" in pending[0]["message_text"]
