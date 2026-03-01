"""Command profile executor — runs linter, build (and future profiles) as subprocesses."""

import asyncio
import structlog

logger = structlog.get_logger(__name__)


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
            )
            stdout_bytes, stderr_bytes = await proc.communicate()

    except TimeoutError:
        if proc is not None:
            proc.kill()
            await proc.wait()
        logger.warning(
            "lint_profile_timeout",
            repo_path=repo_path,
            timeout_seconds=timeout_seconds,
        )
        raise

    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            proc.kill()
            try:
                await asyncio.shield(proc.wait())
            except asyncio.CancelledError:
                pass
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
            )
            stdout_bytes, stderr_bytes = await proc.communicate()

    except TimeoutError:
        if proc is not None:
            proc.kill()
            await proc.wait()
        logger.warning(
            "build_profile_timeout",
            repo_path=repo_path,
            timeout_seconds=timeout_seconds,
        )
        raise

    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            proc.kill()
            try:
                await asyncio.shield(proc.wait())
            except asyncio.CancelledError:
                pass
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
        pattern: Optional test file or pattern appended after the command
                 (e.g. "tests/unit/", "test_broker.py", "-k auth").
                 Empty string means no explicit pattern (run full suite).
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
            )
            stdout_bytes, stderr_bytes = await proc.communicate()

    except TimeoutError:
        if proc is not None:
            proc.kill()
            await proc.wait()
        logger.warning(
            "test_profile_timeout",
            repo_path=repo_path,
            timeout_seconds=timeout_seconds,
        )
        raise

    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            proc.kill()
            try:
                await asyncio.shield(proc.wait())
            except asyncio.CancelledError:
                pass
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
