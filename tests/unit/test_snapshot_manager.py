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

    def test_finds_repo_root_for_non_existent_file(self, manager, fake_repo):
        """M2 fix: non-existent file path correctly resolves repo root (not path/.git/)."""
        # The file doesn't exist on disk but its parent is inside a git repo
        non_existent = str(fake_repo / "new_file_not_yet_created.py")
        root = manager.find_repo_root(non_existent)
        assert root == str(fake_repo)


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


# ---------------------------------------------------------------------------
# list_snapshots
# ---------------------------------------------------------------------------

class TestListSnapshots:
    def test_lists_snapshots_with_timestamps(self, manager, fake_repo):
        """Returns sorted list of snapshot branches with parsed timestamps."""
        # Mock git branch --list output
        git_output = b"  snapshot/edit-2026-02-27-1430\n  snapshot/edit-2026-02-26-0900\n"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=git_output,
                stderr=b"",
            )

            result = manager.list_snapshots(str(fake_repo))

        assert len(result) == 2
        # Should be sorted newest first
        assert result[0]["ref"] == "snapshot/edit-2026-02-27-1430"
        assert "Feb 27, 2026 14:30 UTC" in result[0]["timestamp"]
        assert result[1]["ref"] == "snapshot/edit-2026-02-26-0900"
        assert "Feb 26, 2026 09:00 UTC" in result[1]["timestamp"]

    def test_returns_empty_list_when_no_snapshots(self, manager, fake_repo):
        """Returns empty list when no snapshot branches exist."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"",
                stderr=b"",
            )

            result = manager.list_snapshots(str(fake_repo))

        assert result == []

    def test_raises_on_git_failure(self, manager, fake_repo):
        """Raises list_snapshots_failed when git command fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout=b"",
                stderr=b"fatal: not a git repository",
            )

            with pytest.raises(GitCapabilityError) as exc_info:
                manager.list_snapshots(str(fake_repo))

        assert exc_info.value.code == "list_snapshots_failed"


# ---------------------------------------------------------------------------
# rollback_to_snapshot
# ---------------------------------------------------------------------------

class TestRollbackToSnapshot:
    @pytest.mark.asyncio
    async def test_rollback_restores_files_and_commits(self, manager, fake_repo):
        """Happy path: verifies snapshot, restores files, creates commit."""
        snapshot_ref = "snapshot/edit-2026-02-27-1430"
        operation_id = "abc12345"

        # Mock git commands in sequence:
        # 1. rev-parse --verify (verify snapshot exists) - success
        # 2. checkout <ref> -- . (restore files) - success
        # 3. commit (create rollback commit) - success
        # 4. rev-parse --short HEAD (get commit hash) - returns hash
        # 5. diff-tree (count files) - returns file list

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
            result = await manager.rollback_to_snapshot(
                repo_path=str(fake_repo),
                snapshot_ref=snapshot_ref,
                operation_id=operation_id,
                timeout_seconds=30,
            )

        assert result["snapshot_ref"] == snapshot_ref
        assert result["commit_hash"] == "def456"
        assert result["files_restored"] == 2
        assert call_count == 5

    @pytest.mark.asyncio
    async def test_snapshot_not_found(self, manager, fake_repo):
        """Raises snapshot_not_found when snapshot doesn't exist."""
        process = AsyncMock()
        process.returncode = 128
        process.communicate = AsyncMock(return_value=(b"", b"fatal: Needed a single revision"))

        with patch("asyncio.create_subprocess_exec", return_value=process):
            with pytest.raises(GitCapabilityError) as exc_info:
                await manager.rollback_to_snapshot(
                    repo_path=str(fake_repo),
                    snapshot_ref="snapshot/edit-2026-01-01-0000",
                    operation_id="abc123",
                )

        assert exc_info.value.code == "snapshot_not_found"

    @pytest.mark.asyncio
    async def test_rollback_failed_on_checkout_error(self, manager, fake_repo):
        """Raises rollback_failed when checkout command fails."""
        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            process = AsyncMock()

            if call_count == 1:  # rev-parse --verify succeeds
                process.returncode = 0
                process.communicate = AsyncMock(return_value=(b"abc123\n", b""))
            else:  # checkout fails
                process.returncode = 1
                process.communicate = AsyncMock(return_value=(b"", b"error: pathspec '.' did not match"))

            return process

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            with pytest.raises(GitCapabilityError) as exc_info:
                await manager.rollback_to_snapshot(
                    repo_path=str(fake_repo),
                    snapshot_ref="snapshot/edit-2026-02-27-1430",
                    operation_id="abc123",
                )

        assert exc_info.value.code == "rollback_failed"

    @pytest.mark.asyncio
    async def test_commit_failed(self, manager, fake_repo):
        """Raises commit_failed when commit command fails (not 'nothing to commit')."""
        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            process = AsyncMock()

            if call_count in (1, 2):  # rev-parse and checkout succeed
                process.returncode = 0
                process.communicate = AsyncMock(return_value=(b"abc123\n", b""))
            else:  # commit fails with real error
                process.returncode = 1
                process.communicate = AsyncMock(return_value=(b"", b"fatal: unable to write new commit"))

            return process

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            with pytest.raises(GitCapabilityError) as exc_info:
                await manager.rollback_to_snapshot(
                    repo_path=str(fake_repo),
                    snapshot_ref="snapshot/edit-2026-02-27-1430",
                    operation_id="abc123",
                )

        assert exc_info.value.code == "commit_failed"

    @pytest.mark.asyncio
    async def test_timeout_during_rollback(self, manager, fake_repo):
        """Raises snapshot_timeout when rollback exceeds timeout."""
        process = AsyncMock()
        process.kill = MagicMock()
        process.wait = AsyncMock()
        process.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=process):
            with pytest.raises(GitCapabilityError) as exc_info:
                await manager.rollback_to_snapshot(
                    repo_path=str(fake_repo),
                    snapshot_ref="snapshot/edit-2026-02-27-1430",
                    operation_id="abc123",
                    timeout_seconds=1,
                )

        assert exc_info.value.code == "snapshot_timeout"
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_no_changes_returns_current_head(self, manager, fake_repo):
        """When checkout produces no changes, returns current HEAD without error."""
        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            process = AsyncMock()

            if call_count in (1, 2):  # rev-parse and checkout succeed
                process.returncode = 0
                process.communicate = AsyncMock(return_value=(b"abc123\n", b""))
            elif call_count == 3:  # commit fails with "nothing to commit"
                process.returncode = 1
                process.communicate = AsyncMock(return_value=(b"", b"nothing to commit, working tree clean"))
            elif call_count == 4:  # rev-parse --short HEAD
                process.returncode = 0
                process.communicate = AsyncMock(return_value=(b"abc123\n", b""))

            return process

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await manager.rollback_to_snapshot(
                repo_path=str(fake_repo),
                snapshot_ref="snapshot/edit-2026-02-27-1430",
                operation_id="abc123",
            )

        assert result["snapshot_ref"] == "snapshot/edit-2026-02-27-1430"
        assert result["commit_hash"] == "abc123"
        assert result["files_restored"] == 0
