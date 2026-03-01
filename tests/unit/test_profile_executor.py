"""Unit tests for execute_lint_profile capability."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestExecuteLintProfile:
    """Tests for execute_lint_profile capability function."""

    @pytest.mark.asyncio
    async def test_lint_success_returns_passed_true(self):
        """Lint passes → passed=True, exit_code=0."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_lint_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"All good.", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await execute_lint_profile(
                repo_path="/some/project",
                command="pylint",
                files=["src/"],
                timeout_seconds=60,
            )

        assert result["passed"] is True
        assert result["exit_code"] == 0
        assert "All good." in result["stdout"]
        assert result["stderr"] == ""
        assert result["command_used"] == "pylint"
        assert result["files_linted"] == ["src/"]

    @pytest.mark.asyncio
    async def test_lint_failure_returns_passed_false(self):
        """Lint fails → passed=False, exit_code=1."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_lint_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"error: foo", b"warning: bar"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await execute_lint_profile(
                repo_path="/some/project",
                command="pylint",
                files=["src/"],
                timeout_seconds=60,
            )

        assert result["passed"] is False
        assert result["exit_code"] == 1
        assert "error: foo" in result["stdout"]
        assert "warning: bar" in result["stderr"]

    @pytest.mark.asyncio
    async def test_lint_timeout_raises_timeout_error(self):
        """Subprocess exceeding timeout → TimeoutError raised and process killed."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_lint_profile

        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()

        async def slow_communicate():
            await asyncio.sleep(100)
            return b"", b""

        mock_proc.communicate = slow_communicate

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(TimeoutError):
                await execute_lint_profile(
                    repo_path="/some/project",
                    command="pylint",
                    files=["src/"],
                    timeout_seconds=0,
                )

        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_lint_no_files_runs_against_cwd(self):
        """Empty files list runs command without file args."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_lint_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await execute_lint_profile(
                repo_path="/some/project",
                command="pylint",
                files=[],
                timeout_seconds=60,
            )

        # Called with ["pylint"] only (no file args)
        args_passed = mock_exec.call_args[0]
        assert args_passed == ("pylint",)
        assert result["files_linted"] == []

    @pytest.mark.asyncio
    async def test_lint_command_with_flags_is_split(self):
        """Multi-word command like 'pylint --errors-only' is split correctly."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_lint_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await execute_lint_profile(
                repo_path="/some/project",
                command="pylint --errors-only",
                files=["src/sohnbot/"],
                timeout_seconds=60,
            )

        args_passed = mock_exec.call_args[0]
        assert args_passed == ("pylint", "--errors-only", "src/sohnbot/")

    @pytest.mark.asyncio
    async def test_lint_cwd_set_to_repo_path(self):
        """Subprocess cwd is set to repo_path."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_lint_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await execute_lint_profile(
                repo_path="/some/project",
                command="pylint",
                files=["src/"],
                timeout_seconds=60,
            )

        kwargs = mock_exec.call_args[1]
        assert kwargs["cwd"] == "/some/project"

    @pytest.mark.asyncio
    async def test_lint_stdout_stderr_decoded_with_replace(self):
        """Non-UTF8 bytes in output are decoded with errors='replace'."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_lint_profile

        invalid_utf8 = b"ok \xff\xfe end"
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(invalid_utf8, b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await execute_lint_profile(
                repo_path="/some/project",
                command="pylint",
                files=[],
                timeout_seconds=60,
            )

        # Should not raise, should decode with replacement chars
        assert "ok" in result["stdout"]
        assert isinstance(result["stdout"], str)
