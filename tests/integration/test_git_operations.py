"""Integration tests for git status/diff through broker."""

import subprocess
from pathlib import Path

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.broker import BrokerRouter, ScopeValidator
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager
from src.sohnbot.persistence.notification import get_pending_notifications


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


@pytest.mark.asyncio
async def test_broker_git_checkout_flow_and_execution_log(tmp_path, setup_database):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    target = repo / "a.txt"
    target.write_text("one\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "snapshot/edit-2026-02-27-1430"], cwd=repo, check=True, capture_output=True)
    target.write_text("snapshot\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "snapshot state"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "master"], cwd=repo, check=True, capture_output=True)

    validator = ScopeValidator([str(tmp_path)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="git",
        action="checkout",
        params={"repo_path": str(repo), "branch_name": "snapshot/edit-2026-02-27-1430"},
        chat_id="123",
    )
    assert result.allowed is True
    assert result.tier == 1
    assert result.snapshot_ref is None
    assert result.result["branch"] == "snapshot/edit-2026-02-27-1430"
    assert result.result["commit_hash"]

    head_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_branch == "snapshot/edit-2026-02-27-1430"

    db = await setup_database.get_connection()
    cursor = await db.execute(
        "SELECT capability, action, tier, status FROM execution_log WHERE operation_id = ?",
        (result.operation_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row == ("git", "checkout", 1, "completed")


@pytest.mark.asyncio
async def test_broker_git_commit_flow_execution_log_and_notification(tmp_path, setup_database):
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

    result = await router.route_operation(
        capability="git",
        action="commit",
        params={"repo_path": str(repo), "message": "Fix: Add second line"},
        chat_id="123",
    )

    assert result.allowed is True
    assert result.tier == 1
    assert result.snapshot_ref is None
    assert result.result is not None
    assert result.result["commit_hash"]
    assert result.result["message"] == "Fix: Add second line"
    assert result.result["files_changed"] == 1

    latest_message = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert latest_message == "Fix: Add second line"

    db = await setup_database.get_connection()
    cursor = await db.execute(
        "SELECT capability, action, tier, status FROM execution_log WHERE operation_id = ?",
        (result.operation_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row == ("git", "commit", 1, "completed")

    pending = await get_pending_notifications(limit=10)
    matching = [entry for entry in pending if entry["operation_id"] == result.operation_id]
    assert len(matching) == 1
    message_text = matching[0]["message_text"]
    assert "✅ Commit created:" in message_text
    assert "Message: \"Fix: Add second line\"" in message_text
    assert "Files: 1" in message_text


@pytest.mark.asyncio
async def test_broker_git_prune_snapshots_flow_and_execution_log(tmp_path, setup_database):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    target = repo / "a.txt"
    target.write_text("one\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    old_ref = "snapshot/edit-2020-01-01-0000"
    recent_ref = "snapshot/edit-2099-01-01-0000"
    subprocess.run(["git", "branch", old_ref], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", recent_ref], cwd=repo, check=True, capture_output=True)

    validator = ScopeValidator([str(tmp_path)])
    router = BrokerRouter(validator)

    result = await router.route_operation(
        capability="git",
        action="prune_snapshots",
        params={"repo_path": str(repo), "retention_days": 30},
        chat_id="123",
    )

    assert result.allowed is True
    assert result.tier == 1
    assert result.snapshot_ref is None
    assert result.result is not None
    assert result.result["pruned_count"] == 1
    assert old_ref in result.result["pruned_refs"]
    assert result.result["retained_count"] >= 1

    branches = subprocess.run(
        ["git", "branch", "--list", "snapshot/*"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert old_ref not in branches
    assert recent_ref in branches

    db = await setup_database.get_connection()
    cursor = await db.execute(
        "SELECT capability, action, tier, status FROM execution_log WHERE operation_id = ?",
        (result.operation_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row == ("git", "prune_snapshots", 1, "completed")
