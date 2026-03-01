"""Integration tests for operation logs query flow."""

from pathlib import Path

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.broker import BrokerRouter, ScopeValidator
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager
from src.sohnbot.persistence.operation_logs import query_operation_logs


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
async def test_logs_query_after_file_operation(tmp_path, setup_database):
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    test_file = allowed_root / "test.txt"
    test_file.write_text("hello")

    class _Config:
        def get(self, key):
            if key == "database.path":
                return str(tmp_path / "test.db")
            if key == "files.max_size_mb":
                return 10
            return None

    router = BrokerRouter(ScopeValidator([str(allowed_root)]), config_manager=_Config())

    result = await router.route_operation(
        capability="fs",
        action="read",
        params={"path": str(test_file), "max_size_mb": 10},
        chat_id="chat-1",
    )
    assert result.allowed is True

    logs = await query_operation_logs(str(tmp_path / "test.db"), hours=1)
    assert len(logs) >= 1
    assert any(log["capability"] == "fs" and log["action"] == "read" for log in logs)
