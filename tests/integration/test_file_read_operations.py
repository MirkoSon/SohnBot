"""Integration tests for Story 1.5 file read operations through broker."""

from pathlib import Path

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.broker import BrokerRouter, ScopeValidator
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager


@pytest.fixture
async def setup_database(tmp_path):
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


@pytest.mark.asyncio
async def test_broker_list_files_in_scope_returns_metadata(tmp_path, setup_database):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "notes.txt").write_text("hi")
    (root / ".git").mkdir()
    (root / ".git" / "secret.txt").write_text("secret")

    router = BrokerRouter(ScopeValidator([str(root)]))
    result = await router.route_operation(
        capability="fs",
        action="list",
        params={"path": str(root)},
        chat_id="chat1",
    )

    assert result.allowed is True
    assert result.tier == 0
    assert result.result is not None
    assert result.result["count"] == 1
    assert result.result["files"][0]["path"].endswith("notes.txt")


@pytest.mark.asyncio
async def test_broker_read_rejects_binary_file(tmp_path, setup_database):
    root = tmp_path / "Projects"
    root.mkdir()
    file_path = root / "blob.bin"
    file_path.write_bytes(b"\x00\x01\x02")

    router = BrokerRouter(ScopeValidator([str(root)]))
    result = await router.route_operation(
        capability="fs",
        action="read",
        params={"path": str(file_path)},
        chat_id="chat1",
    )

    assert result.allowed is False
    assert result.error is not None
    assert result.error["code"] == "binary_not_supported"
    assert result.error["message"] == "Binary files not supported"


@pytest.mark.asyncio
async def test_broker_search_respects_scope_and_returns_results(tmp_path, setup_database):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "todo.txt").write_text("alpha\nneedle\n")

    router = BrokerRouter(ScopeValidator([str(root)]))
    result = await router.route_operation(
        capability="fs",
        action="search",
        params={"path": str(root), "pattern": "needle", "timeout_seconds": 5},
        chat_id="chat1",
    )

    assert result.allowed is True
    assert result.tier == 0
    assert result.result is not None
    assert result.result["count"] >= 1
    assert any("needle" in m["content"] for m in result.result["matches"])

