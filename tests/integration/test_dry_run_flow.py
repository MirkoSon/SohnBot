"""Integration tests for profile chaining limit and dry-run flow."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.broker import BrokerRouter, ScopeValidator
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager


@pytest.fixture
async def setup_database(tmp_path):
    db_path = tmp_path / "test.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"
    apply_migrations(db_path, migrations_dir)

    db_manager = DatabaseManager(db_path)
    set_db_manager(db_manager)
    yield db_manager
    await db_manager.close()


@pytest.mark.asyncio
async def test_dry_run_full_flow_returns_preview_and_no_side_effects(tmp_path, setup_database):
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    target = allowed_root / "a.py"
    target.write_text("x = 1\n")

    router = BrokerRouter(ScopeValidator([str(allowed_root)]))
    patch_content = "--- a.py\n+++ a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    result = await router.route_operation(
        capability="fs",
        action="apply_patch",
        params={"path": str(target), "patch": patch_content},
        chat_id="chat-int",
        dry_run=True,
    )

    assert result.allowed is True
    assert result.result["preview"] is True
    assert "DRY RUN" in result.result["message"]
    assert target.read_text() == "x = 1\n"

    db = await setup_database.get_connection()
    cursor = await db.execute("SELECT details FROM execution_log WHERE operation_id = ?", (result.operation_id,))
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    assert '"dry_run": true' in (row[0] or "").lower()


@pytest.mark.asyncio
async def test_profile_limit_integration_enforced(tmp_path, setup_database):
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    router = BrokerRouter(ScopeValidator([str(allowed_root)]))

    with patch(
        "src.sohnbot.capabilities.command_profiles.execute_lint_profile",
        new=AsyncMock(return_value={"passed": True, "exit_code": 0, "stdout": "", "stderr": ""}),
    ):
        for _ in range(5):
            ok = await router.route_operation(
                capability="profiles",
                action="lint",
                params={"repo_path": str(allowed_root), "files": []},
                chat_id="chat-int-limit",
            )
            assert ok.allowed is True

        blocked = await router.route_operation(
            capability="profiles",
            action="lint",
            params={"repo_path": str(allowed_root), "files": []},
            chat_id="chat-int-limit",
        )

    assert blocked.allowed is False
    assert blocked.error["code"] == "profile_chain_limit_exceeded"
