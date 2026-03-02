"""Command profile executor — runs linter, build, test (and future profiles) as subprocesses."""

import asyncio
import json
import os
import signal
import structlog
import sys

logger = structlog.get_logger(__name__)

ALLOWED_PROFILE_COMMANDS = frozenset(
    {
        "pylint",
        "flake8",
        "ruff",
        "eslint",
        "mypy",
        "black",
        "isort",
        "pytest",
        "python",
        "npm",
        "npx",
        "node",
        "make",
        "cargo",
        "go",
        "rg",
        "tsc",
        "prettier",
        "biome",
    }
)


def _validate_command(command: str) -> tuple[bool, str]:
    """Validate command binary against safe allowlist and traversal checks."""
    stripped = (command or "").strip()
    if not stripped:
        return False, "Command must not be empty"

    binary = stripped.split()[0]
    if "/" in binary or "\\" in binary or ".." in binary:
        return False, "Command binary must not contain path separators or traversal tokens"
    if binary not in ALLOWED_PROFILE_COMMANDS:
        return False, f"Command '{binary}' is not in the allowed profile command list"
    return True, ""


async def _kill_process_group(proc: asyncio.subprocess.Process, grace_seconds: float = 0.5) -> None:
    """Terminate subprocess tree; SIGTERM first, then SIGKILL fallback on POSIX."""
    if proc.returncode is not None:
        return

    if sys.platform != "win32":
        try:
            pgid = os.getpgid(proc.pid)
        except (TypeError, ProcessLookupError, PermissionError, OSError):
            pgid = None

        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass

            try:
                await asyncio.wait_for(proc.wait(), timeout=grace_seconds)
                return
            except asyncio.TimeoutError:
                pass
            except (ProcessLookupError, PermissionError, OSError):
                return

            if proc.returncode is None:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass

    if proc.returncode is None:
        proc.kill()

    await proc.wait()


async def execute_lint_profile(
    repo_path: str,
    command: str,
    files: list[str],
    timeout_seconds: int = 60,
) -> dict:
    """Run a lint command as a subprocess with timeout enforcement.

    Args:
        repo_path: Working directory for the subprocess (project root).
        command: Linter command string, e.g. "pylint" or "pylint --errors-only".
                 Multi-word strings are split on whitespace.
        files: List of file/dir arguments appended after the command.
               Empty list runs the linter without explicit file args.
        timeout_seconds: Hard kill timeout in seconds (default 60).

    Returns:
        dict with keys:
            passed (bool): True iff exit_code == 0
            exit_code (int): Subprocess return code
            stdout (str): Decoded standard output
            stderr (str): Decoded standard error
            command_used (str): The command string that was executed
            files_linted (list[str]): The files list that was passed

    Raises:
        TimeoutError: When subprocess exceeds timeout_seconds; process is killed.
    """
    is_valid, error_message = _validate_command(command)
    if not is_valid:
        logger.warning(
            "profile_command_rejected",
            command=command,
            reason=error_message,
            security_event=True,
        )
        raise ValueError(error_message)

    cmd_parts = command.split() + files

    logger.info(
        "lint_profile_started",
        repo_path=repo_path,
        cmd_parts=cmd_parts,
        timeout_seconds=timeout_seconds,
    )

    proc: asyncio.subprocess.Process | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path,
                start_new_session=True,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()

    except TimeoutError:
        if proc is not None and proc.returncode is None:
            await _kill_process_group(proc)
        logger.warning(
            "lint_profile_timeout",
            repo_path=repo_path,
            timeout_seconds=timeout_seconds,
        )
        raise

    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            await _kill_process_group(proc)
        raise

    exit_code = proc.returncode
    passed = exit_code == 0

    logger.info(
        "lint_profile_completed",
        repo_path=repo_path,
        exit_code=exit_code,
        passed=passed,
    )

    return {
        "passed": passed,
        "exit_code": exit_code,
        "stdout": stdout_bytes.decode("utf-8", errors="replace"),
        "stderr": stderr_bytes.decode("utf-8", errors="replace"),
        "command_used": command,
        "files_linted": files,
    }


async def execute_build_profile(
    repo_path: str,
    command: str,
    target: str,
    timeout_seconds: int = 300,
) -> dict:
    """Run a build command as a subprocess with timeout enforcement.

    Args:
        repo_path: Working directory for the subprocess (project root).
        command: Build command string, e.g. "make" or "npm run build".
                 Multi-word strings are split on whitespace.
        target: Optional build target appended after the command (e.g. "dist", "all").
                Empty string means no explicit target.
        timeout_seconds: Hard kill timeout in seconds (default 300).

    Returns:
        dict with keys:
            passed (bool): True iff exit_code == 0
            exit_code (int): Subprocess return code
            stdout (str): Decoded standard output
            stderr (str): Decoded standard error
            command_used (str): The command string that was executed
            target (str): The build target that was passed

    Raises:
        TimeoutError: When subprocess exceeds timeout_seconds; process is killed.
    """
    is_valid, error_message = _validate_command(command)
    if not is_valid:
        logger.warning(
            "profile_command_rejected",
            command=command,
            reason=error_message,
            security_event=True,
        )
        raise ValueError(error_message)

    cmd_parts = command.split()
    if target:
        cmd_parts.append(target)

    logger.info(
        "build_profile_started",
        repo_path=repo_path,
        cmd_parts=cmd_parts,
        timeout_seconds=timeout_seconds,
    )

    proc: asyncio.subprocess.Process | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path,
                start_new_session=True,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()

    except TimeoutError:
        if proc is not None and proc.returncode is None:
            await _kill_process_group(proc)
        logger.warning(
            "build_profile_timeout",
            repo_path=repo_path,
            timeout_seconds=timeout_seconds,
        )
        raise

    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            await _kill_process_group(proc)
        raise

    exit_code = proc.returncode
    passed = exit_code == 0

    logger.info(
        "build_profile_completed",
        repo_path=repo_path,
        exit_code=exit_code,
        passed=passed,
    )

    return {
        "passed": passed,
        "exit_code": exit_code,
        "stdout": stdout_bytes.decode("utf-8", errors="replace"),
        "stderr": stderr_bytes.decode("utf-8", errors="replace"),
        "command_used": command,
        "target": target,
    }


async def execute_test_profile(
    repo_path: str,
    command: str,
    pattern: str,
    timeout_seconds: int = 600,
) -> dict:
    """Run a test command as a subprocess with timeout enforcement.

    Args:
        repo_path: Working directory for the subprocess (project root).
        command: Test command string, e.g. "pytest" or "cargo test".
                 Multi-word strings are split on whitespace.
        pattern: Optional single test path or expression appended after the command
                 (e.g. "tests/unit/", "test_broker.py"). Passed as one argument;
                 multi-word pytest flags like "-k expr" require splitting into
                 separate invocations. Empty string runs the full suite.
        timeout_seconds: Hard kill timeout in seconds (default 600).

    Returns:
        dict with keys:
            passed (bool): True iff exit_code == 0
            exit_code (int): Subprocess return code
            stdout (str): Decoded standard output
            stderr (str): Decoded standard error
            command_used (str): The command string that was executed
            pattern (str): The test pattern that was passed

    Raises:
        TimeoutError: When subprocess exceeds timeout_seconds; process is killed.
    """
    is_valid, error_message = _validate_command(command)
    if not is_valid:
        logger.warning(
            "profile_command_rejected",
            command=command,
            reason=error_message,
            security_event=True,
        )
        raise ValueError(error_message)

    cmd_parts = command.split()
    if pattern:
        cmd_parts.append(pattern)

    logger.info(
        "test_profile_started",
        repo_path=repo_path,
        cmd_parts=cmd_parts,
        timeout_seconds=timeout_seconds,
    )

    proc: asyncio.subprocess.Process | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path,
                start_new_session=True,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()

    except TimeoutError:
        if proc is not None and proc.returncode is None:
            await _kill_process_group(proc)
        logger.warning(
            "test_profile_timeout",
            repo_path=repo_path,
            timeout_seconds=timeout_seconds,
        )
        raise

    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            await _kill_process_group(proc)
        raise

    exit_code = proc.returncode
    passed = exit_code == 0

    logger.info(
        "test_profile_completed",
        repo_path=repo_path,
        exit_code=exit_code,
        passed=passed,
    )

    return {
        "passed": passed,
        "exit_code": exit_code,
        "stdout": stdout_bytes.decode("utf-8", errors="replace"),
        "stderr": stderr_bytes.decode("utf-8", errors="replace"),
        "command_used": command,
        "pattern": pattern,
    }


async def execute_ripgrep_profile(
    repo_path: str,
    pattern: str,
    file_types: list[str] | None = None,
    timeout_seconds: int = 30,
    command: str = "rg",
) -> dict:
    """Run ripgrep search with JSON output parsing and timeout enforcement."""
    is_valid, error_message = _validate_command(command)
    if not is_valid:
        logger.warning(
            "profile_command_rejected",
            command=command,
            reason=error_message,
            security_event=True,
        )
        raise ValueError(error_message)

    cmd_parts = [command, "--json"]
    if file_types:
        for file_type in file_types:
            cmd_parts.extend(["-t", str(file_type)])
    cmd_parts.append(pattern)

    logger.info(
        "ripgrep_profile_started",
        repo_path=repo_path,
        pattern=pattern,
        file_types=file_types,
        timeout_seconds=timeout_seconds,
        command=command,
    )

    proc: asyncio.subprocess.Process | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path,
                start_new_session=True,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()

    except TimeoutError:
        if proc is not None and proc.returncode is None:
            await _kill_process_group(proc)
        logger.warning(
            "ripgrep_profile_timeout",
            repo_path=repo_path,
            pattern=pattern,
            timeout_seconds=timeout_seconds,
        )
        raise

    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            await _kill_process_group(proc)
        raise

    exit_code = int(proc.returncode)
    matches: list[dict] = []
    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")

    for line in stdout_text.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if entry.get("type") != "match":
                continue
            data = entry.get("data") or {}
            file_path = ((data.get("path") or {}).get("text") or "").strip()
            line_number = data.get("line_number")
            line_text = ((data.get("lines") or {}).get("text") or "").rstrip("\n")
            if file_path and line_number is not None:
                matches.append(
                    {
                        "file": file_path,
                        "line": int(line_number),
                        "text": line_text,
                    }
                )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.debug("ripgrep_json_parse_error", error=str(exc))
            continue

    logger.info(
        "ripgrep_profile_completed",
        repo_path=repo_path,
        pattern=pattern,
        total_matches=len(matches),
        exit_code=exit_code,
    )

    return {
        "matches": matches,
        "total_matches": len(matches),
        "exit_code": exit_code,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "command_used": " ".join(cmd_parts),
        "pattern": pattern,
        "file_types": file_types or [],
    }
