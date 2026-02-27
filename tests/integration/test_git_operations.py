"""Integration tests for git status/diff through broker."""

import subprocess
from pathlib import Path

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


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)


@pytest.mark.asyncio
async def test_broker_git_status_and_diff_flow(tmp_path, setup_database):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    target = repo / "a.txt"
    target.write_text("one\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    target.write_text("one\ntwo\n")

    validator = ScopeValidator([str(tmp_path)])
    router = BrokerRouter(validator)

    status_result = await router.route_operation(
        capability="git",
        action="status",
        params={"repo_path": str(repo)},
        chat_id="123",
    )
    assert status_result.allowed is True
    assert status_result.tier == 0
    assert "a.txt" in " ".join(status_result.result["modified"] + status_result.result["staged"])

    diff_result = await router.route_operation(
        capability="git",
        action="diff",
        params={"repo_path": str(repo), "diff_type": "working_tree"},
        chat_id="123",
    )
    assert diff_result.allowed is True
    assert diff_result.tier == 0
    assert "diff --git" in diff_result.result["diff"]
