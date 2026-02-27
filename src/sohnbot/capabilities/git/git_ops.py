"""Git status and diff operations."""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
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


def _validate_local_branch(branch_name: str) -> None:
    if branch_name.startswith(("origin/", "remotes/", "refs/remotes/")):
        raise GitCapabilityError(
            code="invalid_branch",
            message="Branch checkout restricted to local branches only. Remote checkout not permitted.",
            details={"branch_name": branch_name},
            retryable=False,
        )
    if "../" in branch_name or "..\\" in branch_name:
        raise GitCapabilityError(
            code="invalid_branch",
            message="Invalid branch name",
            details={"branch_name": branch_name},
            retryable=False,
        )
    if any(token in branch_name for token in ("~", "^", "@{")):
        raise GitCapabilityError(
            code="invalid_branch",
            message="Branch checkout requires simple local branch names only.",
            details={"branch_name": branch_name},
            retryable=False,
        )
    if branch_name.startswith(("/", "-")):
        raise GitCapabilityError(
            code="invalid_branch",
            message="Invalid branch name format",
            details={"branch_name": branch_name},
            retryable=False,
        )
    if not re.match(r"^[a-zA-Z0-9_][a-zA-Z0-9_/-]*$", branch_name):
        raise GitCapabilityError(
            code="invalid_branch",
            message="Invalid branch name format",
            details={"branch_name": branch_name},
            retryable=False,
        )


async def git_checkout(
    repo_path: str,
    branch_name: str,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    """Checkout a local branch and return resulting branch and commit hash."""
    _validate_local_branch(branch_name)

    try:
        await _run_git_command(
            cmd=["git", "-C", repo_path, "switch", "--", branch_name],
            repo_path=repo_path,
            timeout_seconds=timeout_seconds,
            timeout_code="checkout_timeout",
        )
    except GitCapabilityError as exc:
        if exc.code == "git_command_failed":
            stderr = (exc.details or {}).get("stderr", "")
            lower = str(stderr).lower()
            if "pathspec" in lower or "did not match any file" in lower or "invalid reference" in lower:
                raise GitCapabilityError(
                    code="checkout_failed",
                    message="Branch checkout failed. Branch does not exist locally.",
                    details={"repo_path": repo_path, "branch_name": branch_name, "stderr": stderr},
                    retryable=False,
                ) from exc
            raise GitCapabilityError(
                code="checkout_failed",
                message="Branch checkout failed",
                details={"repo_path": repo_path, "branch_name": branch_name, "stderr": stderr},
                retryable=False,
            ) from exc
        if exc.code == "checkout_timeout":
            raise
        raise

    head_stdout, _ = await _run_git_command(
        cmd=["git", "-C", repo_path, "rev-parse", "--short", "HEAD"],
        repo_path=repo_path,
        timeout_seconds=5,
        timeout_code="checkout_timeout",
    )

    return {
        "branch": branch_name,
        "commit_hash": head_stdout.strip(),
    }


def _validate_commit_message(message: str) -> None:
    msg = (message or "").strip()
    if not msg:
        raise GitCapabilityError(
            code="invalid_commit_message",
            message="Commit message cannot be empty",
            details={"message": message},
            retryable=False,
        )

    # Accept "Type: Summary" and "[Type]: Summary" for compatibility.
    pattern = r"^(?:\[(Fix|Feat|Refactor|Docs|Test|Chore|Style)\]|(Fix|Feat|Refactor|Docs|Test|Chore|Style)):\s+.+$"
    if not re.match(pattern, msg):
        raise GitCapabilityError(
            code="invalid_commit_message",
            message="Commit message must follow format: [Type]: [Summary]",
            details={"message": message, "expected_format": "[Type]: [Summary]"},
            retryable=False,
        )

    first_line = msg.split("\n", 1)[0]
    if len(first_line) > 72:
        raise GitCapabilityError(
            code="invalid_commit_message",
            message="Commit message first line should be <= 72 characters",
            details={"message": message, "length": len(first_line)},
            retryable=False,
        )
    if len(msg) > 4096:
        raise GitCapabilityError(
            code="invalid_commit_message",
            message="Commit message must be <= 4096 characters",
            details={"message_length": len(msg), "max_length": 4096},
            retryable=False,
        )


def _validate_commit_file_path(repo_path: str, file_path: str) -> str:
    """
    Validate and normalize a commit path to a repo-relative path.

    This rejects traversal, option-like paths, and targets outside the repo root.
    """
    path = (file_path or "").strip()
    if not path:
        raise GitCapabilityError(
            code="invalid_commit_file_path",
            message="Commit file path cannot be empty",
            details={"file_path": file_path},
            retryable=False,
        )
    if path.startswith("-"):
        raise GitCapabilityError(
            code="invalid_commit_file_path",
            message="Commit file path cannot start with '-'",
            details={"file_path": file_path},
            retryable=False,
        )

    repo_root = Path(repo_path).resolve(strict=False)
    candidate = Path(path)
    absolute_candidate = (repo_root / candidate).resolve(strict=False) if not candidate.is_absolute() else candidate.resolve(strict=False)

    try:
        rel = absolute_candidate.relative_to(repo_root)
    except ValueError as exc:
        raise GitCapabilityError(
            code="invalid_commit_file_path",
            message="Commit file path must be inside repository root",
            details={"file_path": file_path, "repo_path": repo_path},
            retryable=False,
        ) from exc

    if any(part == ".." for part in rel.parts):
        raise GitCapabilityError(
            code="invalid_commit_file_path",
            message="Commit file path cannot contain parent traversal segments",
            details={"file_path": file_path},
            retryable=False,
        )

    return str(rel)


async def git_commit(
    repo_path: str,
    message: str,
    file_paths: list[str] | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Create a git commit with optional scoped file staging."""
    _validate_commit_message(message)

    if file_paths:
        for path in file_paths:
            normalized_path = _validate_commit_file_path(repo_path, path)
            await _run_git_command(
                cmd=["git", "-C", repo_path, "add", "--", normalized_path],
                repo_path=repo_path,
                timeout_seconds=10,
                timeout_code="commit_timeout",
            )
    else:
        # Safer default than add -A: stage tracked-file modifications/deletions only.
        await _run_git_command(
            cmd=["git", "-C", repo_path, "add", "-u"],
            repo_path=repo_path,
            timeout_seconds=10,
            timeout_code="commit_timeout",
        )

    try:
        await _run_git_command(
            cmd=["git", "-C", repo_path, "commit", "-m", message],
            repo_path=repo_path,
            timeout_seconds=timeout_seconds,
            timeout_code="commit_timeout",
        )
    except GitCapabilityError as exc:
        if exc.code == "git_command_failed":
            stderr = ((exc.details or {}).get("stderr", "") or "").lower()
            if "nothing to commit" in stderr or "no changes added to commit" in stderr:
                return {
                    "commit_hash": None,
                    "message": "No changes to commit",
                    "files_changed": 0,
                }
            raise GitCapabilityError(
                code="commit_failed",
                message="Git commit failed",
                details={"repo_path": repo_path, "stderr": (exc.details or {}).get("stderr", "")},
                retryable=False,
            ) from exc
        if exc.code == "commit_timeout":
            raise
        raise

    hash_stdout, _ = await _run_git_command(
        cmd=["git", "-C", repo_path, "rev-parse", "--short", "HEAD"],
        repo_path=repo_path,
        timeout_seconds=5,
        timeout_code="commit_timeout",
    )
    files_stdout, _ = await _run_git_command(
        cmd=["git", "-C", repo_path, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
        repo_path=repo_path,
        timeout_seconds=5,
        timeout_code="commit_timeout",
    )
    files_changed = len([line for line in files_stdout.splitlines() if line.strip()])

    return {
        "commit_hash": hash_stdout.strip(),
        "message": message,
        "files_changed": files_changed,
    }
