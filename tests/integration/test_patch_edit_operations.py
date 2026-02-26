"""Integration tests for patch-based file edit with snapshot creation (Story 1.6)."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.sohnbot.broker import BrokerRouter, ScopeValidator
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager
from scripts.migrate import apply_migrations


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def setup_database(tmp_path):
    """Set up test database with migrations."""
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
def git_repo(tmp_path):
    """Create a minimal fake git repo with a .git directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


SIMPLE_PATCH = (
    "--- original.txt\n+++ original.txt\n"
    "@@ -1,3 +1,3 @@\n line1\n-line2\n+line2_modified\n line3\n"
)


# ---------------------------------------------------------------------------
# AC: Full broker route, snapshot_ref populated, status = completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_patch_success_snapshot_ref_populated(git_repo, setup_database):
    """Full broker route: apply_patch → snapshot created → status=completed, snapshot_ref set."""
    target = git_repo / "original.txt"
    target.write_text("line1\nline2\nline3\n")

    patch_content = SIMPLE_PATCH.replace("original.txt", target.name)

    validator = ScopeValidator([str(git_repo)])
    router = BrokerRouter(validator)

    # Mock snapshot_manager so no real git is needed
    with patch.object(
        router.snapshot_manager,
        "find_repo_root",
        return_value=str(git_repo),
    ), patch.object(
        router.snapshot_manager,
        "create_snapshot",
        new=AsyncMock(return_value="snapshot/edit-2026-02-26-1200"),
    ):
        result = await router.route_operation(
            capability="fs",
            action="apply_patch",
            params={"path": str(target), "patch": patch_content},
            chat_id="test_chat",
        )

    assert result.allowed is True
    assert result.tier == 1
    assert result.snapshot_ref == "snapshot/edit-2026-02-26-1200"
    assert result.result is not None
    assert result.result["lines_added"] == 1
    assert result.result["lines_removed"] == 1

    # Verify DB: execution_log.snapshot_ref is populated
    # Schema order: operation_id[0], timestamp[1], capability[2], action[3],
    #               chat_id[4], tier[5], status[6], file_paths[7],
    #               snapshot_ref[8], duration_ms[9], error_details[10], details[11]
    db = await setup_database.get_connection()
    cursor = await db.execute(
        "SELECT * FROM execution_log WHERE operation_id = ?",
        (result.operation_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    assert row[6] == "completed"                              # status
    assert row[8] == "snapshot/edit-2026-02-26-1200"         # snapshot_ref


@pytest.mark.asyncio
async def test_apply_patch_file_modified_on_disk(git_repo, setup_database):
    """After successful patch, file content is actually changed on disk."""
    target = git_repo / "app.txt"
    target.write_text("line1\nline2\nline3\n")

    patch_content = SIMPLE_PATCH.replace("original.txt", target.name)

    validator = ScopeValidator([str(git_repo)])
    router = BrokerRouter(validator)

    with patch.object(router.snapshot_manager, "find_repo_root", return_value=str(git_repo)), \
         patch.object(router.snapshot_manager, "create_snapshot", new=AsyncMock(return_value="snapshot/edit-2026-02-26-1200")):
        result = await router.route_operation(
            capability="fs",
            action="apply_patch",
            params={"path": str(target), "patch": patch_content},
            chat_id="test_chat",
        )

    assert result.allowed is True
    content = target.read_text()
    assert "line2_modified" in content
    assert "line2\n" not in content


@pytest.mark.asyncio
async def test_apply_patch_tier_1_classification(git_repo, setup_database):
    """apply_patch with single file path is classified as Tier 1."""
    target = git_repo / "file.txt"
    target.write_text("line1\nline2\nline3\n")

    patch_content = SIMPLE_PATCH.replace("original.txt", target.name)

    validator = ScopeValidator([str(git_repo)])
    router = BrokerRouter(validator)

    with patch.object(router.snapshot_manager, "find_repo_root", return_value=str(git_repo)), \
         patch.object(router.snapshot_manager, "create_snapshot", new=AsyncMock(return_value="snapshot/edit-test")):
        result = await router.route_operation(
            capability="fs",
            action="apply_patch",
            params={"path": str(target), "patch": patch_content},
            chat_id="test_chat",
        )

    assert result.tier == 1


# ---------------------------------------------------------------------------
# AC: Scope violation blocks BEFORE snapshot is created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_violation_blocks_before_snapshot(git_repo, setup_database):
    """Scope violation returns denied BEFORE snapshot is attempted."""
    allowed_root = git_repo / "allowed"
    allowed_root.mkdir()

    outside_file = git_repo / "outside.txt"
    outside_file.write_text("content\n")

    validator = ScopeValidator([str(allowed_root)])
    router = BrokerRouter(validator)

    snapshot_called = False

    async def mock_create_snapshot(*args, **kwargs):
        nonlocal snapshot_called
        snapshot_called = True
        return "snapshot/edit-should-not-happen"

    with patch.object(router.snapshot_manager, "create_snapshot", side_effect=mock_create_snapshot):
        result = await router.route_operation(
            capability="fs",
            action="apply_patch",
            params={"path": str(outside_file), "patch": SIMPLE_PATCH},
            chat_id="test_chat",
        )

    assert result.allowed is False
    assert result.error["code"] == "scope_violation"
    assert snapshot_called is False  # Snapshot must NOT have been attempted


# ---------------------------------------------------------------------------
# AC: Missing patch param returns invalid_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_patch_missing_patch_param(git_repo, setup_database):
    """Missing 'patch' parameter returns invalid_request without snapshot."""
    target = git_repo / "file.txt"
    target.write_text("content\n")

    validator = ScopeValidator([str(git_repo)])
    router = BrokerRouter(validator)

    with patch.object(router.snapshot_manager, "create_snapshot", new=AsyncMock()) as mock_snap:
        result = await router.route_operation(
            capability="fs",
            action="apply_patch",
            params={"path": str(target)},  # 'patch' param missing
            chat_id="test_chat",
        )
        mock_snap.assert_not_called()

    assert result.allowed is False
    assert result.error["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_apply_patch_missing_path_param(git_repo, setup_database):
    """Missing 'path' parameter returns invalid_request."""
    validator = ScopeValidator([str(git_repo)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="fs",
        action="apply_patch",
        params={"patch": SIMPLE_PATCH},  # 'path' missing
        chat_id="test_chat",
    )

    assert result.allowed is False
    assert result.error["code"] == "invalid_request"


# ---------------------------------------------------------------------------
# AC: Best-effort notifier called on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notifier_called_on_successful_patch(git_repo, setup_database):
    """Best-effort notifier is called after successful apply_patch."""
    target = git_repo / "file.txt"
    target.write_text("line1\nline2\nline3\n")

    patch_content = SIMPLE_PATCH.replace("original.txt", target.name)

    notification_calls = []

    async def fake_notifier(chat_id: str, message: str) -> None:
        notification_calls.append((chat_id, message))

    validator = ScopeValidator([str(git_repo)])
    router = BrokerRouter(validator, notifier=fake_notifier)

    with patch.object(router.snapshot_manager, "find_repo_root", return_value=str(git_repo)), \
         patch.object(router.snapshot_manager, "create_snapshot", new=AsyncMock(return_value="snapshot/edit-test")):
        result = await router.route_operation(
            capability="fs",
            action="apply_patch",
            params={"path": str(target), "patch": patch_content},
            chat_id="chat_42",
        )

    assert result.allowed is True
    assert len(notification_calls) == 1
    chat_id, message = notification_calls[0]
    assert chat_id == "chat_42"
    assert "Patch applied" in message
    assert "snapshot/edit-test" in message


@pytest.mark.asyncio
async def test_notifier_failure_does_not_block_result(git_repo, setup_database):
    """Notifier failure must NOT affect the BrokerResult."""
    target = git_repo / "file.txt"
    target.write_text("line1\nline2\nline3\n")

    patch_content = SIMPLE_PATCH.replace("original.txt", target.name)

    async def crashing_notifier(chat_id: str, message: str) -> None:
        raise RuntimeError("notification service down")

    validator = ScopeValidator([str(git_repo)])
    router = BrokerRouter(validator, notifier=crashing_notifier)

    with patch.object(router.snapshot_manager, "find_repo_root", return_value=str(git_repo)), \
         patch.object(router.snapshot_manager, "create_snapshot", new=AsyncMock(return_value="snapshot/edit-test")):
        result = await router.route_operation(
            capability="fs",
            action="apply_patch",
            params={"path": str(target), "patch": patch_content},
            chat_id="chat_42",
        )

    # Despite notifier crash, operation succeeded
    assert result.allowed is True
    assert result.snapshot_ref == "snapshot/edit-test"
