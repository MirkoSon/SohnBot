"""Unit tests for git status/diff capability operations."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sohnbot.capabilities.git.git_ops import git_checkout, git_commit, git_diff, git_status
from src.sohnbot.capabilities.git.snapshot_manager import GitCapabilityError


class _FakeProcess:
    def __init__(self, returncode: int, stdout: bytes, stderr: bytes):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.kill = MagicMock()
        self.wait = AsyncMock()

    async def communicate(self):
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_git_status_success_parse():
    out = (
        "# branch.head main\n"
        "# branch.ab +2 -1\n"
        "1 M. N... 100644 100644 100644 a a src/a.py\n"
        "1 .M N... 100644 100644 100644 a a src/b.py\n"
        "? src/new.py\n"
    ).encode()
    proc = _FakeProcess(0, out, b"")
    with patch("src.sohnbot.capabilities.git.git_ops.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        data = await git_status("/repo")
    assert data["branch"] == "main"
    assert data["ahead"] == 2
    assert data["behind"] == 1
    assert "src/a.py" in data["staged"]
    assert "src/b.py" in data["modified"]
    assert "src/new.py" in data["untracked"]


@pytest.mark.asyncio
async def test_git_status_non_git_directory_error():
    proc = _FakeProcess(128, b"", b"fatal: not a git repository")
    with patch("src.sohnbot.capabilities.git.git_ops.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(GitCapabilityError) as exc_info:
            await git_status("/not-repo")
    assert exc_info.value.code == "not_a_git_repo"


@pytest.mark.asyncio
async def test_git_status_git_binary_not_found():
    with patch(
        "src.sohnbot.capabilities.git.git_ops.asyncio.create_subprocess_exec",
        AsyncMock(side_effect=FileNotFoundError()),
    ):
        with pytest.raises(GitCapabilityError) as exc_info:
            await git_status("/repo")
    assert exc_info.value.code == "git_not_found"


@pytest.mark.asyncio
async def test_git_status_timeout_handling():
    proc = _FakeProcess(0, b"", b"")

    async def _slow_communicate():
        await asyncio.sleep(0.05)
        return b"", b""

    proc.communicate = _slow_communicate
    with patch("src.sohnbot.capabilities.git.git_ops.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(GitCapabilityError) as exc_info:
            await git_status("/repo", timeout_seconds=0.001)
    assert exc_info.value.code == "git_status_timeout"
    proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_git_diff_working_tree_vs_staged():
    diff_text = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n".encode()
    proc = _FakeProcess(0, diff_text, b"")
    with patch("src.sohnbot.capabilities.git.git_ops.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        data = await git_diff("/repo")
    assert "diff --git" in data["diff"]
    assert data["diff_type"] == "working_tree"


@pytest.mark.asyncio
async def test_git_diff_staged_vs_head():
    proc = _FakeProcess(0, b"diff --git a/a.py b/a.py\n", b"")
    with patch("src.sohnbot.capabilities.git.git_ops.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        data = await git_diff("/repo", diff_type="staged")
    assert data["diff_type"] == "staged"


@pytest.mark.asyncio
async def test_git_diff_commit_to_commit():
    proc = _FakeProcess(0, b"diff --git a/a.py b/a.py\n", b"")
    with patch("src.sohnbot.capabilities.git.git_ops.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        data = await git_diff("/repo", diff_type="commit", commit_refs=["HEAD~1", "HEAD"])
    assert data["commit_refs"] == ["HEAD~1", "HEAD"]


@pytest.mark.asyncio
async def test_git_diff_binary_file_handling():
    proc = _FakeProcess(0, b"Binary files a/img.bin and b/img.bin differ\n", b"")
    with patch("src.sohnbot.capabilities.git.git_ops.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        data = await git_diff("/repo")
    assert "Binary files" in data["diff"]


@pytest.mark.asyncio
async def test_git_status_porcelain_v2_rename_tab_paths():
    out = (
        "# branch.head main\n"
        "2 R. N... 100644 100644 100644 123 456 R100\told/name.txt\tnew/name.txt\n"
    ).encode()
    proc = _FakeProcess(0, out, b"")
    with patch("src.sohnbot.capabilities.git.git_ops.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        data = await git_status("/repo")
    assert "new/name.txt" in data["staged"]


@pytest.mark.asyncio
async def test_git_checkout_success_case():
    with patch(
        "src.sohnbot.capabilities.git.git_ops._run_git_command",
        AsyncMock(side_effect=[("Switched to branch 'main'\n", ""), ("abc123\n", "")]),
    ) as mock_run:
        data = await git_checkout("/repo", "main")
    assert data["branch"] == "main"
    assert data["commit_hash"] == "abc123"
    first_cmd = mock_run.await_args_list[0].kwargs["cmd"]
    assert first_cmd == ["git", "-C", "/repo", "switch", "--", "main"]


@pytest.mark.asyncio
async def test_git_checkout_local_branch_validation_valid_cases():
    async def _mock_run(**kwargs):
        cmd = kwargs.get("cmd", [])
        if cmd and cmd[-2:] == ["--short", "HEAD"]:
            return ("abc123\n", "")
        return ("", "")

    with patch(
        "src.sohnbot.capabilities.git.git_ops._run_git_command",
        AsyncMock(side_effect=_mock_run),
    ):
        for branch in ("main", "feature/new-feature", "snapshot/edit-2026-02-27-1430"):
            data = await git_checkout("/repo", branch)
            assert data["branch"] == branch


@pytest.mark.asyncio
async def test_git_checkout_remote_branch_rejection_invalid_cases():
    for branch in ("origin/main", "remotes/origin/feature", "refs/remotes/origin/main"):
        with pytest.raises(GitCapabilityError) as exc_info:
            await git_checkout("/repo", branch)
        assert exc_info.value.code == "invalid_branch"


@pytest.mark.asyncio
async def test_git_checkout_path_traversal_rejection():
    for branch in ("../main", "..\\main"):
        with pytest.raises(GitCapabilityError) as exc_info:
            await git_checkout("/repo", branch)
        assert exc_info.value.code == "invalid_branch"


@pytest.mark.asyncio
async def test_git_checkout_rejects_branch_starting_with_slash_or_dash():
    for branch in ("/main", "-main"):
        with pytest.raises(GitCapabilityError) as exc_info:
            await git_checkout("/repo", branch)
        assert exc_info.value.code == "invalid_branch"


@pytest.mark.asyncio
async def test_git_checkout_non_existent_branch_error():
    with patch(
        "src.sohnbot.capabilities.git.git_ops._run_git_command",
        AsyncMock(
            side_effect=GitCapabilityError(
                code="git_command_failed",
                message="Git command failed",
                details={"stderr": "error: pathspec 'nope' did not match any file(s) known to git"},
                retryable=False,
            )
        ),
    ):
        with pytest.raises(GitCapabilityError) as exc_info:
            await git_checkout("/repo", "nope")
    assert exc_info.value.code == "checkout_failed"


@pytest.mark.asyncio
async def test_git_checkout_timeout_handling():
    with patch(
        "src.sohnbot.capabilities.git.git_ops._run_git_command",
        AsyncMock(
            side_effect=GitCapabilityError(
                code="checkout_timeout",
                message="timed out",
                details={"repo_path": "/repo"},
                retryable=True,
            )
        ),
    ):
        with pytest.raises(GitCapabilityError) as exc_info:
            await git_checkout("/repo", "main", timeout_seconds=1)
    assert exc_info.value.code == "checkout_timeout"


@pytest.mark.asyncio
async def test_git_commit_success_case():
    with patch(
        "src.sohnbot.capabilities.git.git_ops._run_git_command",
        AsyncMock(side_effect=[("", ""), ("[main] commit\n", ""), ("abc123\n", ""), ("a.py\nb.py\n", "")]),
    ):
        data = await git_commit("/repo", "Fix: Resolve lint issue")
    assert data["commit_hash"] == "abc123"
    assert data["files_changed"] == 2
    assert data["message"] == "Fix: Resolve lint issue"


@pytest.mark.asyncio
async def test_git_commit_with_specific_file_paths():
    with patch(
        "src.sohnbot.capabilities.git.git_ops._run_git_command",
        AsyncMock(side_effect=[("", ""), ("", ""), ("", ""), ("abc123\n", ""), ("a.py\n", "")]),
    ) as mock_run:
        data = await git_commit("/repo", "Feat: Add feature", file_paths=["a.py", "b.py"])
    assert data["files_changed"] == 1
    add_calls = [call.kwargs["cmd"] for call in mock_run.await_args_list if call.kwargs["cmd"][3] == "add"]
    assert add_calls[0] == ["git", "-C", "/repo", "add", "--", "a.py"]
    assert add_calls[1] == ["git", "-C", "/repo", "add", "--", "b.py"]


@pytest.mark.asyncio
async def test_git_commit_with_all_changes_file_paths_none():
    with patch(
        "src.sohnbot.capabilities.git.git_ops._run_git_command",
        AsyncMock(side_effect=[("", ""), ("", ""), ("abc123\n", ""), ("a.py\n", "")]),
    ) as mock_run:
        await git_commit("/repo", "Chore: Update housekeeping", file_paths=None)
    first_cmd = mock_run.await_args_list[0].kwargs["cmd"]
    assert first_cmd == ["git", "-C", "/repo", "add", "-u"]


@pytest.mark.asyncio
async def test_git_commit_nothing_to_commit_graceful():
    with patch(
        "src.sohnbot.capabilities.git.git_ops._run_git_command",
        AsyncMock(
            side_effect=[
                ("", ""),
                GitCapabilityError(
                    code="git_command_failed",
                    message="Git command failed",
                    details={"stderr": "nothing to commit, working tree clean"},
                    retryable=False,
                ),
            ]
        ),
    ):
        data = await git_commit("/repo", "Fix: No-op change")
    assert data["commit_hash"] is None
    assert data["files_changed"] == 0


@pytest.mark.asyncio
async def test_git_commit_invalid_message_format():
    with pytest.raises(GitCapabilityError) as exc_info:
        await git_commit("/repo", "invalid message")
    assert exc_info.value.code == "invalid_commit_message"


@pytest.mark.asyncio
async def test_git_commit_empty_message_rejection():
    with pytest.raises(GitCapabilityError) as exc_info:
        await git_commit("/repo", " ")
    assert exc_info.value.code == "invalid_commit_message"


@pytest.mark.asyncio
async def test_git_commit_timeout_handling():
    with patch(
        "src.sohnbot.capabilities.git.git_ops._run_git_command",
        AsyncMock(
            side_effect=GitCapabilityError(
                code="commit_timeout",
                message="timed out",
                details={"repo_path": "/repo"},
                retryable=True,
            )
        ),
    ):
        with pytest.raises(GitCapabilityError) as exc_info:
            await git_commit("/repo", "Fix: Timeout", timeout_seconds=1)
    assert exc_info.value.code == "commit_timeout"


@pytest.mark.asyncio
async def test_git_commit_git_binary_not_found():
    with patch(
        "src.sohnbot.capabilities.git.git_ops._run_git_command",
        AsyncMock(
            side_effect=GitCapabilityError(
                code="git_not_found",
                message="git CLI is required",
                details={},
                retryable=False,
            )
        ),
    ):
        with pytest.raises(GitCapabilityError) as exc_info:
            await git_commit("/repo", "Fix: Missing git")
    assert exc_info.value.code == "git_not_found"


@pytest.mark.asyncio
async def test_git_commit_rejects_outside_repo_file_path():
    with pytest.raises(GitCapabilityError) as exc_info:
        await git_commit("/repo", "Fix: Scoped commit", file_paths=["../outside.txt"])
    assert exc_info.value.code == "invalid_commit_file_path"


@pytest.mark.asyncio
async def test_git_commit_rejects_option_like_file_path():
    with pytest.raises(GitCapabilityError) as exc_info:
        await git_commit("/repo", "Fix: Scoped commit", file_paths=["-p"])
    assert exc_info.value.code == "invalid_commit_file_path"


@pytest.mark.asyncio
async def test_git_commit_rejects_too_long_total_message():
    long_summary = "a" * 4090
    with pytest.raises(GitCapabilityError) as exc_info:
        await git_commit("/repo", f"Fix: {long_summary}")
    assert exc_info.value.code == "invalid_commit_message"
