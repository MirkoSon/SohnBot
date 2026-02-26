"""Unit tests for SnapshotManager git capability."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sohnbot.capabilities.git.snapshot_manager import GitCapabilityError, SnapshotManager


@pytest.fixture
def manager():
    return SnapshotManager()


@pytest.fixture
def fake_repo(tmp_path):
    """Create a fake git repo directory."""
    (tmp_path / ".git").mkdir()
    target_file = tmp_path / "somefile.py"
    target_file.write_text("hello\n")
    return tmp_path


# ---------------------------------------------------------------------------
# find_repo_root
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    def test_finds_git_dir_in_parent(self, manager, fake_repo):
        """Walks up from a file path and finds .git directory."""
        file_path = str(fake_repo / "somefile.py")
        root = manager.find_repo_root(file_path)
        assert root == str(fake_repo)

    def test_finds_git_dir_nested(self, manager, fake_repo):
        """Handles nested subdirectory paths."""
        sub = fake_repo / "src" / "pkg"
        sub.mkdir(parents=True)
        file_path = str(sub / "module.py")
        root = manager.find_repo_root(file_path)
        assert root == str(fake_repo)

    def test_not_a_git_repo_raises(self, manager, tmp_path):
        """Raises not_a_git_repo when no .git found."""
        no_git = tmp_path / "no_git_here"
        no_git.mkdir()
        with pytest.raises(GitCapabilityError) as exc_info:
            manager.find_repo_root(str(no_git / "file.txt"))
        assert exc_info.value.code == "not_a_git_repo"
        assert exc_info.value.retryable is False


# ---------------------------------------------------------------------------
# create_snapshot — happy path
# ---------------------------------------------------------------------------

class TestCreateSnapshotHappyPath:
    @pytest.mark.asyncio
    async def test_creates_snapshot_branch(self, manager, fake_repo):
        """Calls git branch with snapshot/edit-YYYY-MM-DD-HHMM naming."""
        process_mock = AsyncMock()
        process_mock.returncode = 0
        process_mock.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=process_mock) as mock_exec:
            result = await manager.create_snapshot(
                repo_path=str(fake_repo),
                operation_id="abc12345",
                timeout_seconds=5,
            )

        # Branch name format: snapshot/edit-YYYY-MM-DD-HHMM
        assert result.startswith("snapshot/edit-")
        parts = result.split("snapshot/edit-")[1].split("-")
        # Expect: YYYY-MM-DD-HHMM (4 parts minimum)
        assert len(parts) >= 4

        # Verify git was called with correct args
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "git"
        assert call_args[1] == "-C"
        assert call_args[2] == str(fake_repo)
        assert call_args[3] == "branch"

    @pytest.mark.asyncio
    async def test_handles_name_collision_with_suffix(self, manager, fake_repo):
        """On collision ('already exists'), retries with operation_id suffix."""
        # First call: already exists → returncode 128
        process_collision = AsyncMock()
        process_collision.returncode = 128
        process_collision.communicate = AsyncMock(
            return_value=(b"", b"fatal: A branch named 'snapshot/edit-2026-02-26-1200' already exists")
        )
        # Second call: success
        process_success = AsyncMock()
        process_success.returncode = 0
        process_success.communicate = AsyncMock(return_value=(b"", b""))

        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return process_collision
            return process_success

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await manager.create_snapshot(
                repo_path=str(fake_repo),
                operation_id="abc12345",
            )

        assert call_count == 2
        # Second attempt appends operation_id prefix
        assert "abc1" in result


# ---------------------------------------------------------------------------
# create_snapshot — error conditions
# ---------------------------------------------------------------------------

class TestCreateSnapshotErrors:
    @pytest.mark.asyncio
    async def test_git_not_found(self, manager, fake_repo):
        """FileNotFoundError from subprocess → git_not_found error code."""
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("git not found"),
        ):
            with pytest.raises(GitCapabilityError) as exc_info:
                await manager.create_snapshot(
                    repo_path=str(fake_repo),
                    operation_id="abc12345",
                )
        assert exc_info.value.code == "git_not_found"
        assert exc_info.value.retryable is False

    @pytest.mark.asyncio
    async def test_snapshot_timeout(self, manager, fake_repo):
        """asyncio.TimeoutError → snapshot_timeout error code."""
        process_mock = AsyncMock()
        process_mock.kill = MagicMock()
        process_mock.wait = AsyncMock()
        process_mock.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=process_mock):
            with pytest.raises(GitCapabilityError) as exc_info:
                await manager.create_snapshot(
                    repo_path=str(fake_repo),
                    operation_id="abc12345",
                    timeout_seconds=1,
                )
        assert exc_info.value.code == "snapshot_timeout"
        assert exc_info.value.retryable is True
        process_mock.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_snapshot_creation_failed(self, manager, fake_repo):
        """Non-zero returncode without 'already exists' → snapshot_creation_failed."""
        process_mock = AsyncMock()
        process_mock.returncode = 1
        process_mock.communicate = AsyncMock(
            return_value=(b"", b"fatal: some other git error")
        )

        with patch("asyncio.create_subprocess_exec", return_value=process_mock):
            with pytest.raises(GitCapabilityError) as exc_info:
                await manager.create_snapshot(
                    repo_path=str(fake_repo),
                    operation_id="abc12345",
                )
        assert exc_info.value.code == "snapshot_creation_failed"
        assert exc_info.value.retryable is False


# ---------------------------------------------------------------------------
# GitCapabilityError shape
# ---------------------------------------------------------------------------

class TestGitCapabilityErrorShape:
    def test_to_dict_returns_required_shape(self):
        """to_dict() matches {code, message, details, retryable} shape."""
        err = GitCapabilityError(
            code="git_not_found",
            message="git CLI not available",
            details={"repo_path": "/foo"},
            retryable=False,
        )
        d = err.to_dict()
        assert d == {
            "code": "git_not_found",
            "message": "git CLI not available",
            "details": {"repo_path": "/foo"},
            "retryable": False,
        }

    def test_details_defaults_to_empty_dict(self):
        """details=None should serialize as empty dict."""
        err = GitCapabilityError(code="x", message="y")
        assert err.to_dict()["details"] == {}
