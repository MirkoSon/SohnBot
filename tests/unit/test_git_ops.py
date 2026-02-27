"""Unit tests for git status/diff capability operations."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sohnbot.capabilities.git.git_ops import git_diff, git_status
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
