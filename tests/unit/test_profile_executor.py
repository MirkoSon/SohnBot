"""Unit tests for execute_lint_profile, execute_build_profile, and execute_test_profile capabilities."""

import asyncio
import signal
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
        mock_proc.wait.assert_called_once()

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


class TestExecuteBuildProfile:
    """Tests for execute_build_profile capability function."""

    @pytest.mark.asyncio
    async def test_build_success_returns_passed_true(self):
        """Build passes → passed=True, exit_code=0."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_build_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"Build complete.", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await execute_build_profile(
                repo_path="/some/project",
                command="make",
                target="all",
                timeout_seconds=300,
            )

        assert result["passed"] is True
        assert result["exit_code"] == 0
        assert "Build complete." in result["stdout"]
        assert result["stderr"] == ""
        assert result["command_used"] == "make"
        assert result["target"] == "all"

    @pytest.mark.asyncio
    async def test_build_failure_returns_passed_false(self):
        """Build fails → passed=False, exit_code=2."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_build_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 2
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Error: compilation failed"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await execute_build_profile(
                repo_path="/some/project",
                command="make",
                target="",
                timeout_seconds=300,
            )

        assert result["passed"] is False
        assert result["exit_code"] == 2
        assert "compilation failed" in result["stderr"]

    @pytest.mark.asyncio
    async def test_build_timeout_raises_and_kills_process(self):
        """Subprocess exceeding timeout → TimeoutError raised, process killed and waited."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_build_profile

        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()

        async def slow_communicate():
            await asyncio.sleep(100)
            return b"", b""

        mock_proc.communicate = slow_communicate

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(TimeoutError):
                await execute_build_profile(
                    repo_path="/some/project",
                    command="make",
                    target="dist",
                    timeout_seconds=0,
                )

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_no_target_runs_command_only(self):
        """Empty target runs command without target arg appended."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_build_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await execute_build_profile(
                repo_path="/some/project",
                command="make",
                target="",
                timeout_seconds=300,
            )

        args_passed = mock_exec.call_args[0]
        assert args_passed == ("make",)
        assert result["target"] == ""

    @pytest.mark.asyncio
    async def test_build_with_target_appended_to_command(self):
        """Target string is appended to command args."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_build_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await execute_build_profile(
                repo_path="/some/project",
                command="make",
                target="dist",
                timeout_seconds=300,
            )

        args_passed = mock_exec.call_args[0]
        assert args_passed == ("make", "dist")

    @pytest.mark.asyncio
    async def test_build_multi_word_command_split(self):
        """Multi-word command like 'npm run build' is split correctly."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_build_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await execute_build_profile(
                repo_path="/some/project",
                command="npm run build",
                target="",
                timeout_seconds=300,
            )

        args_passed = mock_exec.call_args[0]
        assert args_passed == ("npm", "run", "build")

    @pytest.mark.asyncio
    async def test_build_cwd_set_to_repo_path(self):
        """Subprocess cwd is set to repo_path."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_build_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await execute_build_profile(
                repo_path="/some/project",
                command="make",
                target="",
                timeout_seconds=300,
            )

        kwargs = mock_exec.call_args[1]
        assert kwargs["cwd"] == "/some/project"

    @pytest.mark.asyncio
    async def test_build_cancellation_kills_process(self):
        """CancelledError while running subprocess kills and waits the process (no zombie)."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_build_profile

        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()
        mock_proc.returncode = None  # Process still running

        async def blocking_communicate():
            await asyncio.sleep(100)
            return b"", b""

        mock_proc.communicate = blocking_communicate

        async def run_and_cancel():
            task = asyncio.create_task(
                execute_build_profile(
                    repo_path="/some/project",
                    command="make",
                    target="dist",
                    timeout_seconds=60,
                )
            )
            await asyncio.sleep(0)  # Let the coroutine start
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_and_cancel()

        mock_proc.kill.assert_called_once()


class TestExecuteLintProfileCancellation:
    """Test CancelledError cleanup for execute_lint_profile."""

    @pytest.mark.asyncio
    async def test_lint_cancellation_kills_process(self):
        """CancelledError while running subprocess kills and waits the process (no zombie)."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_lint_profile

        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()
        mock_proc.returncode = None  # Process still running

        async def blocking_communicate():
            await asyncio.sleep(100)
            return b"", b""

        mock_proc.communicate = blocking_communicate

        async def run_and_cancel():
            task = asyncio.create_task(
                execute_lint_profile(
                    repo_path="/some/project",
                    command="pylint",
                    files=[],
                    timeout_seconds=60,
                )
            )
            await asyncio.sleep(0)  # Let the coroutine start
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_and_cancel()

        mock_proc.kill.assert_called_once()


class TestExecuteTestProfile:
    """Tests for execute_test_profile capability function."""

    @pytest.mark.asyncio
    async def test_test_success_returns_passed_true(self):
        """Test suite passes → passed=True, exit_code=0."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_test_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"5 passed.", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await execute_test_profile(
                repo_path="/some/project",
                command="pytest",
                pattern="tests/unit/",
                timeout_seconds=600,
            )

        assert result["passed"] is True
        assert result["exit_code"] == 0
        assert "5 passed." in result["stdout"]
        assert result["stderr"] == ""
        assert result["command_used"] == "pytest"
        assert result["pattern"] == "tests/unit/"

    @pytest.mark.asyncio
    async def test_test_failure_returns_passed_false(self):
        """Test suite fails → passed=False, exit_code=1."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_test_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"2 failed, 3 passed.", b"AssertionError"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await execute_test_profile(
                repo_path="/some/project",
                command="pytest",
                pattern="",
                timeout_seconds=600,
            )

        assert result["passed"] is False
        assert result["exit_code"] == 1
        assert "2 failed" in result["stdout"]
        assert "AssertionError" in result["stderr"]

    @pytest.mark.asyncio
    async def test_test_timeout_raises_and_kills_process(self):
        """Subprocess exceeding timeout → TimeoutError raised, process killed and waited."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_test_profile

        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()

        async def slow_communicate():
            await asyncio.sleep(100)
            return b"", b""

        mock_proc.communicate = slow_communicate

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(TimeoutError):
                await execute_test_profile(
                    repo_path="/some/project",
                    command="pytest",
                    pattern="",
                    timeout_seconds=0,
                )

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_test_no_pattern_runs_full_suite(self):
        """Empty pattern runs command without pattern arg appended."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_test_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await execute_test_profile(
                repo_path="/some/project",
                command="pytest",
                pattern="",
                timeout_seconds=600,
            )

        args_passed = mock_exec.call_args[0]
        assert args_passed == ("pytest",)
        assert result["pattern"] == ""

    @pytest.mark.asyncio
    async def test_test_with_pattern_appended_to_command(self):
        """Pattern string is appended to command args."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_test_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await execute_test_profile(
                repo_path="/some/project",
                command="pytest",
                pattern="tests/unit/test_broker.py",
                timeout_seconds=600,
            )

        args_passed = mock_exec.call_args[0]
        assert args_passed == ("pytest", "tests/unit/test_broker.py")

    @pytest.mark.asyncio
    async def test_test_cwd_set_to_repo_path(self):
        """Subprocess cwd is set to repo_path."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_test_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await execute_test_profile(
                repo_path="/some/project",
                command="pytest",
                pattern="",
                timeout_seconds=600,
            )

        kwargs = mock_exec.call_args[1]
        assert kwargs["cwd"] == "/some/project"

    @pytest.mark.asyncio
    async def test_test_cancellation_kills_process(self):
        """CancelledError while running subprocess kills and waits the process (no zombie)."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_test_profile

        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()
        mock_proc.returncode = None  # Process still running

        async def blocking_communicate():
            await asyncio.sleep(100)
            return b"", b""

        mock_proc.communicate = blocking_communicate

        async def run_and_cancel():
            task = asyncio.create_task(
                execute_test_profile(
                    repo_path="/some/project",
                    command="pytest",
                    pattern="",
                    timeout_seconds=60,
                )
            )
            await asyncio.sleep(0)  # Let the coroutine start
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_and_cancel()

        mock_proc.kill.assert_called_once()


class TestExecuteRipgrepProfile:
    """Tests for execute_ripgrep_profile capability function."""

    @pytest.mark.asyncio
    async def test_ripgrep_success_parses_json_matches(self):
        """Ripgrep JSON output should be parsed into structured matches."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_ripgrep_profile

        stdout = (
            b'{"type":"begin","data":{"path":{"text":"src/a.py"}}}\n'
            b'{"type":"match","data":{"path":{"text":"src/a.py"},"line_number":12,"lines":{"text":"def foo():\\n"}}}\n'
            b'{"type":"match","data":{"path":{"text":"src/b.py"},"line_number":5,"lines":{"text":"foo = 1\\n"}}}\n'
            b'{"type":"end","data":{"path":{"text":"src/a.py"}}}\n'
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(stdout, b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await execute_ripgrep_profile(
                repo_path="/repo",
                pattern="foo",
                file_types=["py"],
                timeout_seconds=30,
                command="rg",
            )

        args_passed = mock_exec.call_args[0]
        assert args_passed == ("rg", "--json", "-t", "py", "foo")
        assert result["exit_code"] == 0
        assert result["total_matches"] == 2
        assert result["matches"][0]["file"] == "src/a.py"
        assert result["matches"][0]["line"] == 12
        assert "def foo()" in result["matches"][0]["text"]

    @pytest.mark.asyncio
    async def test_ripgrep_no_matches_returns_empty(self):
        """Exit code 1 with no match lines should produce empty match list."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_ripgrep_profile

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await execute_ripgrep_profile(
                repo_path="/repo",
                pattern="missing",
                timeout_seconds=30,
            )

        assert result["exit_code"] == 1
        assert result["total_matches"] == 0
        assert result["matches"] == []

    @pytest.mark.asyncio
    async def test_ripgrep_timeout_raises_and_kills_process(self):
        """Timeout should kill process and raise TimeoutError."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_ripgrep_profile

        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()

        async def slow_communicate():
            await asyncio.sleep(100)
            return b"", b""

        mock_proc.communicate = slow_communicate

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(TimeoutError):
                await execute_ripgrep_profile(
                    repo_path="/repo",
                    pattern="foo",
                    timeout_seconds=0,
                )

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_ripgrep_malformed_json_lines_are_ignored(self):
        """Malformed JSON lines should not crash parsing."""
        from src.sohnbot.capabilities.command_profiles.profile_executor import execute_ripgrep_profile

        stdout = (
            b'{"type":"match","data":{"path":{"text":"src/a.py"},"line_number":1,"lines":{"text":"foo\\n"}}}\n'
            b'{not-json}\n'
            b'{"type":"match","data":{"path":{"text":"src/b.py"},"line_number":2,"lines":{"text":"bar foo\\n"}}}\n'
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(stdout, b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await execute_ripgrep_profile(
                repo_path="/repo",
                pattern="foo",
                timeout_seconds=30,
            )

        assert result["total_matches"] == 2
        assert len(result["matches"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runner", "kwargs"),
    [
        ("execute_lint_profile", {"repo_path": "/repo", "command": "pylint", "files": []}),
        ("execute_build_profile", {"repo_path": "/repo", "command": "make", "target": ""}),
        ("execute_test_profile", {"repo_path": "/repo", "command": "pytest", "pattern": ""}),
        ("execute_ripgrep_profile", {"repo_path": "/repo", "pattern": "needle"}),
    ],
)
async def test_profile_subprocesses_use_start_new_session(runner, kwargs):
    module = __import__(
        "src.sohnbot.capabilities.command_profiles.profile_executor",
        fromlist=[runner],
    )
    fn = getattr(module, runner)

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await fn(**kwargs)

    assert mock_exec.call_args.kwargs["start_new_session"] is True


@pytest.mark.asyncio
async def test_timeout_kills_process_group_on_posix():
    from src.sohnbot.capabilities.command_profiles.profile_executor import execute_lint_profile

    mock_proc = AsyncMock()
    mock_proc.pid = 4321
    mock_proc.returncode = None
    mock_proc.wait = AsyncMock(return_value=0)

    async def slow_communicate():
        await asyncio.sleep(100)
        return b"", b""

    mock_proc.communicate = slow_communicate

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("src.sohnbot.capabilities.command_profiles.profile_executor.os.getpgid", return_value=4321),
        patch("src.sohnbot.capabilities.command_profiles.profile_executor.os.killpg") as mock_killpg,
    ):
        with pytest.raises(TimeoutError):
            await execute_lint_profile(
                repo_path="/repo",
                command="pylint",
                files=[],
                timeout_seconds=0,
            )

    assert mock_killpg.call_count >= 1
    first_call = mock_killpg.call_args_list[0]
    assert first_call.args == (4321, signal.SIGTERM)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runner", "kwargs"),
    [
        ("execute_lint_profile", {"repo_path": "/repo", "command": "/usr/bin/pylint", "files": []}),
        ("execute_build_profile", {"repo_path": "/repo", "command": "../make", "target": ""}),
        ("execute_test_profile", {"repo_path": "/repo", "command": "evil-binary", "pattern": ""}),
        ("execute_ripgrep_profile", {"repo_path": "/repo", "pattern": "needle", "command": "C:\\\\rg.exe"}),
    ],
)
async def test_disallowed_profile_commands_are_rejected_and_logged(runner, kwargs):
    module = __import__(
        "src.sohnbot.capabilities.command_profiles.profile_executor",
        fromlist=[runner],
    )
    fn = getattr(module, runner)

    with patch("src.sohnbot.capabilities.command_profiles.profile_executor.logger.warning") as mock_warn:
        with pytest.raises(ValueError):
            await fn(**kwargs)

    mock_warn.assert_called_once()
    assert mock_warn.call_args.args[0] == "profile_command_rejected"


@pytest.mark.asyncio
async def test_allowed_ripgrep_command_is_accepted():
    from src.sohnbot.capabilities.command_profiles.profile_executor import execute_ripgrep_profile

    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await execute_ripgrep_profile(
            repo_path="/repo",
            pattern="needle",
            command="rg",
        )

    assert result["command_used"].startswith("rg ")
