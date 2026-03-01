"""Command profile executor — runs linter (and future profiles) as subprocesses."""

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
        logger.warning(
            "lint_profile_timeout",
            repo_path=repo_path,
            timeout_seconds=timeout_seconds,
        )
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
