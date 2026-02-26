"""Unit tests for file operations capability."""

import asyncio
from pathlib import Path

import pytest

from src.sohnbot.capabilities.files.file_ops import FileCapabilityError, FileOps


def test_list_files_includes_metadata_and_excludes_dirs(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("a")
    (root / ".git").mkdir()
    (root / ".git" / "hidden.txt").write_text("hidden")
    (root / ".venv").mkdir()
    (root / ".venv" / "venv.txt").write_text("hidden")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "mod.js").write_text("hidden")

    file_ops = FileOps()
    result = file_ops.list_files(str(root))

    assert result["count"] == 1
    assert len(result["files"]) == 1
    file_entry = result["files"][0]
    assert file_entry["path"].endswith("a.txt")
    assert isinstance(file_entry["size"], int)
    assert isinstance(file_entry["modified_at"], int)


def test_read_file_success(tmp_path):
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello world")
    file_ops = FileOps()

    result = file_ops.read_file(str(file_path), max_size_mb=10)

    assert result["content"] == "hello world"
    assert result["size"] == len("hello world")
    assert result["path"] == str(file_path)


def test_read_file_rejects_oversize(tmp_path):
    file_path = tmp_path / "big.txt"
    file_path.write_text("x" * 2048)
    file_ops = FileOps()

    with pytest.raises(FileCapabilityError) as exc:
        file_ops.read_file(str(file_path), max_size_mb=0)

    err = exc.value.to_dict()
    assert err["code"] == "file_too_large"
    assert "exceeds" in err["message"].lower()


def test_read_file_rejects_binary(tmp_path):
    file_path = tmp_path / "bin.dat"
    file_path.write_bytes(b"\x00\x01\x02")
    file_ops = FileOps()

    with pytest.raises(FileCapabilityError) as exc:
        file_ops.read_file(str(file_path), max_size_mb=10)

    err = exc.value.to_dict()
    assert err["code"] == "binary_not_supported"
    assert err["message"] == "Binary files not supported"


@pytest.mark.asyncio
async def test_search_files_returns_matches(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_text("alpha\nneedle\nomega\n")
    file_ops = FileOps()

    result = await file_ops.search_files(str(root), "needle", timeout_seconds=5)

    assert result["count"] >= 1
    assert any("needle" in item["content"] for item in result["matches"])


@pytest.mark.asyncio
async def test_search_files_timeout(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_text("needle")
    file_ops = FileOps()

    class DummyProcess:
        returncode = 0

        async def communicate(self):
            await asyncio.sleep(0.05)
            return b"", b""

        def kill(self):
            return None

        async def wait(self):
            return 0

    async def fake_subprocess_exec(*_args, **_kwargs):
        return DummyProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)

    with pytest.raises(FileCapabilityError) as exc:
        await file_ops.search_files(str(root), "needle", timeout_seconds=0)

    err = exc.value.to_dict()
    assert err["code"] == "search_timeout"

