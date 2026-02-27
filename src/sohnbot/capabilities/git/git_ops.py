"""Git status and diff operations."""

from __future__ import annotations

import asyncio
from typing import Any

from .snapshot_manager import GitCapabilityError


async def _run_git_command(
    cmd: list[str],
    repo_path: str,
    timeout_seconds: int,
    timeout_code: str,
) -> tuple[str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise GitCapabilityError(
            code="git_not_found",
            message=(
                "git CLI is required for git operations. "
                "See docs/development_environment.md for installation instructions."
            ),
            details={"repo_path": repo_path},
            retryable=False,
        ) from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise GitCapabilityError(
            code=timeout_code,
            message=f"Git command timed out after {timeout_seconds}s",
            details={"repo_path": repo_path, "command": cmd},
            retryable=True,
        ) from exc

    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        lower = stderr.lower()
        if "not a git repository" in lower:
            raise GitCapabilityError(
                code="not_a_git_repo",
                message="Path is not a git repository",
                details={"repo_path": repo_path, "stderr": stderr},
                retryable=False,
            )
        raise GitCapabilityError(
            code="git_command_failed",
            message="Git command failed",
            details={"repo_path": repo_path, "command": cmd, "stderr": stderr},
            retryable=False,
        )

    return stdout, stderr


def _parse_porcelain_v2(output: str) -> dict[str, Any]:
    branch = "HEAD"
    ahead = 0
    behind = 0
    modified: list[str] = []
    staged: list[str] = []
    untracked: list[str] = []

    def _extract_path(line: str) -> str:
        # Official porcelain v2 record paths are tab-delimited after metadata.
        if "\t" in line:
            path_block = line.split("\t", 1)[1]
            # Rename/copy records can include "old\tnew"; prefer destination path.
            if "\t" in path_block:
                return path_block.split("\t")[-1].strip()
            return path_block.strip()

        # Fallback for non-tab fixtures: parse using field counts.
        # Format "1 ..." has path as 9th token, "2 ..." has path as 10th token.
        tokens = line.split()
        if not tokens:
            return ""
        if tokens[0] == "1" and len(tokens) >= 9:
            return tokens[8]
        if tokens[0] == "2" and len(tokens) >= 10:
            return tokens[9]
        return tokens[-1]

    for raw_line in output.splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            continue
        if line.startswith("# branch.head "):
            branch = line[len("# branch.head "):].strip()
            continue
        if line.startswith("# branch.ab "):
            ab = line[len("# branch.ab "):].strip().split()
            for part in ab:
                if part.startswith("+"):
                    ahead = int(part[1:])
                elif part.startswith("-"):
                    behind = int(part[1:])
            continue
        if line.startswith("? "):
            untracked.append(line[2:].strip())
            continue
        if line.startswith("1 ") or line.startswith("2 "):
            # Porcelain v2 tokens: type + XY + metadata + path(s)
            status = line.split(" ", 2)[1]
            xy = status if len(status) >= 2 else ".."
            path = _extract_path(line)
            if xy[0] != "." and path not in staged:
                staged.append(path)
            if xy[1] != "." and path not in modified:
                modified.append(path)

    return {
        "branch": branch,
        "ahead": ahead,
        "behind": behind,
        "modified": modified,
        "staged": staged,
        "untracked": untracked,
    }


async def git_status(repo_path: str, timeout_seconds: int = 10) -> dict[str, Any]:
    """Return machine-parsed git status for the repository."""
    cmd = ["git", "-C", repo_path, "status", "--porcelain=v2", "--branch"]
    stdout, _ = await _run_git_command(
        cmd=cmd,
        repo_path=repo_path,
        timeout_seconds=timeout_seconds,
        timeout_code="git_status_timeout",
    )
    return _parse_porcelain_v2(stdout)


async def git_diff(
    repo_path: str,
    diff_type: str = "working_tree",
    file_path: str | None = None,
    commit_refs: list[str] | tuple[str, str] | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Return unified diff for supported diff modes."""
    cmd = ["git", "-C", repo_path, "diff"]
    if diff_type == "staged":
        cmd.append("--cached")
    elif diff_type == "commit":
        if not commit_refs or len(commit_refs) != 2:
            raise GitCapabilityError(
                code="invalid_diff_args",
                message="commit diff requires commit_refs with exactly two commit refs",
                details={"diff_type": diff_type, "commit_refs": commit_refs},
                retryable=False,
            )
        cmd.extend([commit_refs[0], commit_refs[1]])
    elif diff_type != "working_tree":
        raise GitCapabilityError(
            code="invalid_diff_type",
            message="diff_type must be one of: working_tree, staged, commit",
            details={"diff_type": diff_type},
            retryable=False,
        )

    if file_path:
        cmd.extend(["--", file_path])

    stdout, _ = await _run_git_command(
        cmd=cmd,
        repo_path=repo_path,
        timeout_seconds=timeout_seconds,
        timeout_code="git_diff_timeout",
    )
    return {
        "repo_path": repo_path,
        "diff_type": diff_type,
        "file_path": file_path,
        "commit_refs": list(commit_refs) if commit_refs else None,
        "diff": stdout,
    }
