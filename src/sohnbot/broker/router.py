"""Broker router - central routing and policy enforcement."""

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional
import structlog

from ..capabilities.files import FileCapabilityError, FileOps, PatchEditor
from ..capabilities.git import (
    GitCapabilityError,
    SnapshotManager,
    git_checkout,
    git_commit,
    git_diff,
    git_status,
)
from ..capabilities.scheduler import (
    create_job,
    delete_job,
    disable_job,
    edit_job,
    enable_job,
    get_job_by_name,
    list_jobs,
)
from ..capabilities.web import WebCapabilityError, brave_search
from .operation_classifier import classify_tier
from .scope_validator import ScopeValidator
from ..persistence.audit import log_operation_start, log_operation_end
from ..persistence.db import get_db
from ..persistence.notification import (
    enqueue_notification,
    get_notifications_enabled,
)
from ..persistence.operation_logs import query_operation_logs
from ..config.manager import ConfigManager
from ..config.registry import _SAFE_COMMAND_RE as _SAFE_PROFILE_RE

logger = structlog.get_logger(__name__)
_OBSERVE_LOG_STATUS_FILTERS = {"in_progress", "completed", "failed", "postponed", "cancelled"}


@dataclass
class BrokerResult:
    """Result of broker policy decision and operation execution."""

    allowed: bool
    operation_id: str
    tier: Optional[int] = None
    snapshot_ref: Optional[str] = None
    error: Optional[dict] = None
    result: Optional[dict] = None


class BrokerRouter:
    """Central routing and policy enforcement for all capabilities."""

    def __init__(
        self,
        scope_validator: ScopeValidator,
        config_manager: Optional[ConfigManager] = None,
    ):
        """
        Initialize broker router.

        Args:
            scope_validator: ScopeValidator instance for path validation
            config_manager: ConfigManager instance for dynamic configuration (optional for tests)
        """
        self.scope_validator = scope_validator
        self.config_manager = config_manager
        self.file_ops = FileOps(scope_validator=scope_validator)
        self.patch_editor = PatchEditor(scope_validator=scope_validator)
        self.snapshot_manager = SnapshotManager()
        self._state_lock = asyncio.Lock()
        self._operation_start_times: Dict[str, float] = {}
        self._profile_counts: Dict[str, int] = {}

    async def reset_profile_counter(self, chat_id: str) -> None:
        """Reset profile execution counter for a chat/request boundary."""
        async with self._state_lock:
            self._profile_counts.pop(chat_id, None)

    async def get_profile_count(self, chat_id: str) -> int:
        """Get profile execution count for a chat."""
        async with self._state_lock:
            return int(self._profile_counts.get(chat_id, 0))

    async def route_operation(
        self,
        capability: str,
        action: str,
        params: Dict[str, Any],
        chat_id: str,
        dry_run: bool = False,
    ) -> BrokerResult:
        """
        Route operation through broker validation and execution.

        Validation Order (NON-NEGOTIABLE):
        1. Generate operation_id
        2. Classify tier
        3. Validate scope (if file operation)
        4. Check limits
        5. Log operation start
        6. Execute capability (with snapshot if Tier 1/2)
        7. Log operation end

        Args:
            capability: Capability module (fs, git, scheduler, web, profiles, observe)
            action: Operation action (read, patch, commit, etc.)
            params: Operation parameters
            chat_id: Telegram chat ID (user identifier)

        Returns:
            BrokerResult with operation outcome
        """
        # 1. Generate operation tracking ID
        operation_id = str(uuid.uuid4())
        await self._set_operation_start_time(operation_id)

        # 2. Classify operation tier
        file_count = self._count_files(params)
        tier = classify_tier(capability, action, file_count)
        if dry_run:
            tier = 0

        if capability == "profiles":
            max_chain_length = 5
            if self.config_manager:
                try:
                    max_chain_length = int(self.config_manager.get("commands.max_chain_length"))
                except Exception:  # noqa: BLE001
                    pass

            async with self._state_lock:
                current_count = self._profile_counts.get(chat_id, 0)
                if current_count >= max_chain_length:
                    allowed = False
                else:
                    self._profile_counts[chat_id] = current_count + 1
                    updated_count = self._profile_counts[chat_id]
                    allowed = True

            if not allowed:
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "profile_chain_limit_exceeded",
                        "message": (
                            f"Profile execution limit reached ({current_count}/{max_chain_length} used). "
                            "Break request into smaller parts."
                        ),
                        "details": {
                            "current_count": current_count,
                            "max_chain_length": max_chain_length,
                        },
                        "retryable": False,
                    },
                )
            logger.info(
                "profile_counter_incremented",
                chat_id=chat_id,
                count=updated_count,
                max_chain_length=max_chain_length,
            )

        # 3. Validate scope (if file operation)
        if capability == "fs":
            # Validate required parameters
            if action in {"read", "list", "search", "apply_patch"} and "path" not in params:
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "Missing required parameter: path",
                        "details": {"action": action},
                        "retryable": False,
                    },
                )

            # Validate search pattern parameter
            if action == "search":
                pattern = params.get("pattern", "")
                if not pattern or not isinstance(pattern, str):
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": "Missing or invalid required parameter: pattern",
                            "details": {"action": action, "pattern": pattern},
                            "retryable": False,
                        },
                    )

            # Validate patch content parameter
            if action == "apply_patch":
                patch_content = params.get("patch", "")
                if not patch_content or not isinstance(patch_content, str):
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": "Missing or invalid required parameter: patch",
                            "details": {"action": action},
                            "retryable": False,
                        },
                    )

            # Check both singular 'path' and plural 'paths'
            paths_to_validate = []
            if "path" in params:
                paths_to_validate.append(params["path"])
            if "paths" in params and isinstance(params["paths"], list):
                paths_to_validate.extend(params["paths"])

            for path in paths_to_validate:
                is_valid, error_msg = self.scope_validator.validate_path(path)
                if not is_valid:
                    normalized_path = self.scope_validator.get_normalized_path(path)
                    allowed_roots = self.scope_validator.get_allowed_roots()
                    logger.warning(
                        "scope_violation_blocked",
                        operation_id=operation_id,
                        chat_id=chat_id,
                        capability=capability,
                        action=action,
                        attempted_path=str(path),
                        normalized_path=normalized_path,
                        allowed_roots=allowed_roots,
                    )
                    # Clean up operation start time to prevent memory leak
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "scope_violation",
                            "message": error_msg,
                            "details": {
                                "path": str(path),
                                "normalized_path": normalized_path,
                                "allowed_roots": allowed_roots,
                            },
                            "retryable": False,
                        },
                    )

        # Git capability parameter validation and scope checking
        if capability == "git":
            # Validate required parameters
            if action == "commit" and ("repo_path" not in params or "message" not in params):
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "Missing required parameters: repo_path and message",
                        "details": {"action": action},
                        "retryable": False,
                    },
                )

            if action == "checkout" and ("repo_path" not in params or "branch_name" not in params):
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "Missing required parameters: repo_path and branch_name",
                        "details": {"action": action},
                        "retryable": False,
                    },
                )

            if action == "status" and "repo_path" not in params:
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "Missing required parameter: repo_path",
                        "details": {"action": action},
                        "retryable": False,
                    },
                )

            if action == "diff" and "repo_path" not in params:
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "Missing required parameter: repo_path",
                        "details": {"action": action},
                        "retryable": False,
                    },
                )

            if action == "list_snapshots" and "repo_path" not in params:
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "Missing required parameter: repo_path",
                        "details": {"action": action},
                        "retryable": False,
                    },
                )

            if action == "prune_snapshots" and "repo_path" not in params:
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "Missing required parameter: repo_path",
                        "details": {"action": action},
                        "retryable": False,
                    },
                )

            if action == "rollback":
                if "repo_path" not in params or "snapshot_ref" not in params:
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": "Missing required parameters: repo_path and snapshot_ref",
                            "details": {"action": action},
                            "retryable": False,
                        },
                    )

            # Scope validation: repo_path must be within configured roots
            repo_path = params.get("repo_path")
            if repo_path:
                is_valid, error_msg = self.scope_validator.validate_path(repo_path)
                if not is_valid:
                    normalized_path = self.scope_validator.get_normalized_path(repo_path)
                    allowed_roots = self.scope_validator.get_allowed_roots()
                    logger.warning(
                        "scope_violation_blocked",
                        operation_id=operation_id,
                        chat_id=chat_id,
                        capability=capability,
                        action=action,
                        attempted_path=str(repo_path),
                        normalized_path=normalized_path,
                        allowed_roots=allowed_roots,
                    )
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "scope_violation",
                            "message": error_msg,
                            "details": {
                                "path": str(repo_path),
                                "normalized_path": normalized_path,
                                "allowed_roots": allowed_roots,
                            },
                            "retryable": False,
                        },
                    )

        if capability == "scheduler":
            if action == "create":
                required = {"name", "cron_expr", "timezone", "action"}
                missing = sorted([key for key in required if key not in params])
                if missing:
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": f"Missing required parameters: {', '.join(missing)}",
                            "details": {"action": action, "missing": missing},
                            "retryable": False,
                        },
                    )
            if action == "delete" and "job_id" not in params and "name" not in params:
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "Missing required parameter: job_id",
                        "details": {"action": action},
                        "retryable": False,
                    },
                )
            if action in {"disable", "enable"} and "name" not in params and "job_id" not in params:
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "Missing required parameter: name or job_id",
                        "details": {"action": action},
                        "retryable": False,
                    },
                )
            if action == "edit":
                if "name" not in params and "job_id" not in params:
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": "Missing required parameter: name or job_id",
                            "details": {"action": action},
                            "retryable": False,
                        },
                    )
                if "updates" not in params or not isinstance(params.get("updates"), dict):
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": "Missing or invalid required parameter: updates",
                            "details": {"action": action},
                            "retryable": False,
                        },
                    )

        # Profiles capability parameter validation and scope checking
        if capability == "profiles":
            if action in {"lint", "build", "test", "ripgrep"} and "repo_path" not in params:
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "Missing required parameter: repo_path",
                        "details": {"action": action},
                        "retryable": False,
                    },
                )

            repo_path = params.get("repo_path")
            if not repo_path or not str(repo_path).strip():
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "repo_path must not be empty",
                        "details": {"action": action},
                        "retryable": False,
                    },
                )

            is_valid, error_msg = self.scope_validator.validate_path(repo_path)
            if not is_valid:
                normalized_path = self.scope_validator.get_normalized_path(repo_path)
                allowed_roots = self.scope_validator.get_allowed_roots()
                logger.warning(
                    "scope_violation_blocked",
                    operation_id=operation_id,
                    chat_id=chat_id,
                    capability=capability,
                    action=action,
                    attempted_path=str(repo_path),
                    normalized_path=normalized_path,
                    allowed_roots=allowed_roots,
                )
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "scope_violation",
                        "message": error_msg,
                        "details": {
                            "path": str(repo_path),
                            "normalized_path": normalized_path,
                            "allowed_roots": allowed_roots,
                        },
                        "retryable": False,
                    },
                )

            files = params.get("files") or []
            for f in files:
                from pathlib import PurePosixPath
                if ".." in PurePosixPath(str(f)).parts:
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "scope_violation",
                            "message": f"files entry contains path traversal: {f}",
                            "details": {"file": str(f)},
                            "retryable": False,
                        },
                    )

            target = params.get("target") or ""
            if target:
                if not _SAFE_PROFILE_RE.match(target):
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": "target contains disallowed characters",
                            "details": {"target": target},
                            "retryable": False,
                        },
                    )

            pattern = params.get("pattern") or ""
            if pattern:
                from pathlib import PurePosixPath
                if action != "ripgrep" and ".." in PurePosixPath(str(pattern)).parts:
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "scope_violation",
                            "message": f"pattern contains path traversal: {pattern}",
                            "details": {"pattern": pattern},
                            "retryable": False,
                        },
                    )
                if action != "ripgrep" and not _SAFE_PROFILE_RE.match(pattern):
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": "pattern contains disallowed characters",
                            "details": {"pattern": pattern},
                            "retryable": False,
                        },
                    )
            if action == "ripgrep":
                if "pattern" not in params or not isinstance(params.get("pattern"), str) or not params.get("pattern"):
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": "Missing or invalid required parameter: pattern",
                            "details": {"action": action},
                            "retryable": False,
                        },
                    )
                if "file_types" in params and params.get("file_types") is not None:
                    file_types = params.get("file_types")
                    if not isinstance(file_types, list) or not all(isinstance(item, str) for item in file_types):
                        await self._remove_operation_start_time(operation_id)
                        return BrokerResult(
                            allowed=False,
                            operation_id=operation_id,
                            tier=tier,
                            error={
                                "code": "invalid_request",
                                "message": "file_types must be a list of strings",
                                "details": {"action": action},
                                "retryable": False,
                            },
                        )

        if capability == "web":
            if action != "search":
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": f"Unsupported web action: {action}",
                        "details": {"capability": capability, "action": action},
                        "retryable": False,
                    },
                )

            query = params.get("query")
            if not isinstance(query, str) or not query.strip():
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "Missing or invalid required parameter: query",
                        "details": {"action": action},
                        "retryable": False,
                    },
                )
            if len(query.strip()) > 500:
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "Search query exceeds 500 characters",
                        "details": {"query_length": len(query.strip())},
                        "retryable": False,
                    },
                )

            mode = params.get("mode", "fresh")
            if mode not in {"fresh", "static"}:
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "mode must be 'fresh' or 'static'",
                        "details": {"mode": mode},
                        "retryable": False,
                    },
                )

            params["query"] = query.strip()
            params["mode"] = mode

        if capability == "observe":
            if action != "logs":
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": f"Unsupported observe action: {action}",
                        "details": {"capability": capability, "action": action},
                        "retryable": False,
                    },
                )

            try:
                hours = int(params.get("hours", 24))
            except (TypeError, ValueError):
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "hours must be an integer between 1 and 720",
                        "details": {"action": action, "hours": params.get("hours")},
                        "retryable": False,
                    },
                )
            if hours < 1 or hours > 720:
                await self._remove_operation_start_time(operation_id)
                return BrokerResult(
                    allowed=False,
                    operation_id=operation_id,
                    tier=tier,
                    error={
                        "code": "invalid_request",
                        "message": "hours must be an integer between 1 and 720",
                        "details": {"action": action, "hours": hours},
                        "retryable": False,
                    },
                )
            params["hours"] = hours

            if "capability" in params and params.get("capability") is not None:
                capability_filter = params.get("capability")
                if not isinstance(capability_filter, str) or not capability_filter.strip():
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": "capability filter must be a non-empty string",
                            "details": {"action": action, "capability": capability_filter},
                            "retryable": False,
                        },
                    )
                params["capability"] = capability_filter.strip()

            if "status" in params and params.get("status") is not None:
                status_filter = params.get("status")
                if not isinstance(status_filter, str) or status_filter not in _OBSERVE_LOG_STATUS_FILTERS:
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": (
                                "status must be one of: "
                                f"{', '.join(sorted(_OBSERVE_LOG_STATUS_FILTERS))}"
                            ),
                            "details": {"action": action, "status": status_filter},
                            "retryable": False,
                        },
                    )
                params["status"] = status_filter

            if "chat_id" in params and params.get("chat_id") is not None:
                chat_filter = params.get("chat_id")
                if not isinstance(chat_filter, str) or not chat_filter.strip():
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": "chat_id filter must be a non-empty string",
                            "details": {"action": action, "chat_id": chat_filter},
                            "retryable": False,
                        },
                    )
                params["chat_id"] = chat_filter.strip()

            if "tier" in params and params.get("tier") is not None:
                try:
                    tier_filter = int(params["tier"])
                except (TypeError, ValueError):
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": "tier must be one of: 0, 1, 2, 3",
                            "details": {"action": action, "tier": params.get("tier")},
                            "retryable": False,
                        },
                    )
                if tier_filter not in {0, 1, 2, 3}:
                    await self._remove_operation_start_time(operation_id)
                    return BrokerResult(
                        allowed=False,
                        operation_id=operation_id,
                        tier=tier,
                        error={
                            "code": "invalid_request",
                            "message": "tier must be one of: 0, 1, 2, 3",
                            "details": {"action": action, "tier": tier_filter},
                            "retryable": False,
                        },
                    )
                params["tier"] = tier_filter

        # 4. Check limits (e.g., max command profiles per request)
        # TODO: Implement limit checking (Story 1.5+)

        # 5. Log operation start
        await log_operation_start(
            operation_id=operation_id,
            capability=capability,
            action=action,
            chat_id=chat_id,
            tier=tier,
            file_paths=params.get("path") or params.get("paths"),
        )

        # 6. Execute capability (with snapshot if Tier 1/2)
        snapshot_ref = None
        try:
            # Skip snapshot creation for operations that do not modify filesystem state.
            if (
                tier in (1, 2)
                and not (
                    capability == "git"
                    and action in {"rollback", "list_snapshots", "checkout", "commit", "prune_snapshots"}
                )
                and capability != "scheduler"
            ):
                # Create git snapshot branch before execution
                snapshot_ref = await self._create_snapshot(
                    operation_id, file_path=params.get("path")
                )

            # Execute capability with timeout from configuration
            timeout_seconds = (
                self.config_manager.get("broker.operation_timeout_seconds")
                if self.config_manager
                else 300  # Default 5 minutes for tests without config
            )

            async with asyncio.timeout(timeout_seconds):
                if dry_run:
                    result = await self._execute_dry_run_preview(
                        capability=capability,
                        action=action,
                        params=params,
                        operation_id=operation_id,
                    )
                else:
                    result = await self._execute_capability(
                        capability, action, params, operation_id
                    )

            # 7. Log operation end (success)
            duration_ms = await self._calculate_duration(operation_id)
            await log_operation_end(
                operation_id=operation_id,
                status="completed",
                snapshot_ref=snapshot_ref,
                duration_ms=duration_ms,
            )
            if dry_run:
                await self._mark_operation_dry_run(operation_id=operation_id, result=result)

            await self._enqueue_operation_notification(
                operation_id=operation_id,
                chat_id=chat_id,
                capability=capability,
                action=action,
                params=params,
                status="completed",
                snapshot_ref=snapshot_ref,
                result=result,
            )

            return BrokerResult(
                allowed=True,
                operation_id=operation_id,
                tier=tier,
                snapshot_ref=snapshot_ref,
                result=result,
            )

        except asyncio.TimeoutError:
            # Log operation end (timeout)
            duration_ms = await self._calculate_duration(operation_id)
            await log_operation_end(
                operation_id=operation_id,
                status="failed",
                duration_ms=duration_ms,
                error_details={"code": "timeout", "message": "Operation timed out"},
            )
            await self._enqueue_operation_notification(
                operation_id=operation_id,
                chat_id=chat_id,
                capability=capability,
                action=action,
                params=params,
                status="timeout",
                snapshot_ref=snapshot_ref,
                result=None,
            )
            return BrokerResult(
                allowed=False,
                operation_id=operation_id,
                tier=tier,
                error={
                    "code": "timeout",
                    "message": "Operation timed out",
                    "retryable": True,
                },
            )

        except (FileCapabilityError, GitCapabilityError, WebCapabilityError) as e:
            # Log operation end (capability validation/runtime error)
            duration_ms = await self._calculate_duration(operation_id)
            await log_operation_end(
                operation_id=operation_id,
                status="failed",
                duration_ms=duration_ms,
                error_details=e.to_dict(),
            )
            await self._enqueue_operation_notification(
                operation_id=operation_id,
                chat_id=chat_id,
                capability=capability,
                action=action,
                params=params,
                status="failed",
                snapshot_ref=snapshot_ref,
                result=None,
            )
            return BrokerResult(
                allowed=False,
                operation_id=operation_id,
                tier=tier,
                error=e.to_dict(),
            )

        except Exception as e:
            # Log operation end (error)
            duration_ms = await self._calculate_duration(operation_id)
            await log_operation_end(
                operation_id=operation_id,
                status="failed",
                duration_ms=duration_ms,
                error_details={"code": "execution_error", "message": str(e)},
            )
            await self._enqueue_operation_notification(
                operation_id=operation_id,
                chat_id=chat_id,
                capability=capability,
                action=action,
                params=params,
                status="failed",
                snapshot_ref=snapshot_ref,
                result=None,
            )
            return BrokerResult(
                allowed=False,
                operation_id=operation_id,
                tier=tier,
                error={
                    "code": "execution_error",
                    "message": str(e),
                    "retryable": False,
                },
            )

    def _count_files(self, params: Dict[str, Any]) -> int:
        """
        Count number of files affected by operation.

        Args:
            params: Operation parameters

        Returns:
            Number of files (0 if no files specified)
        """
        if "path" in params:
            return 1
        elif "paths" in params and isinstance(params["paths"], list):
            return len(params["paths"])
        return 0

    async def _set_operation_start_time(self, operation_id: str) -> None:
        async with self._state_lock:
            self._operation_start_times[operation_id] = datetime.now().timestamp()

    async def _remove_operation_start_time(self, operation_id: str) -> None:
        async with self._state_lock:
            self._operation_start_times.pop(operation_id, None)

    async def _calculate_duration(self, operation_id: str) -> int:
        async with self._state_lock:
            if operation_id in self._operation_start_times:
                start_time = self._operation_start_times[operation_id]
                duration_seconds = datetime.now().timestamp() - start_time
                del self._operation_start_times[operation_id]
                return int(duration_seconds * 1000)
            return 0

    async def _create_snapshot(
        self, operation_id: str, file_path: Optional[str] = None
    ) -> str:
        """
        Create git snapshot branch before execution via SnapshotManager.

        Args:
            operation_id: Operation UUID for snapshot naming
            file_path: Path of the file being modified (used to find repo root)

        Returns:
            Snapshot branch reference
        """
        if not file_path:
            raise GitCapabilityError(
                code="snapshot_skipped",
                message="No file path provided — cannot determine git repo for snapshot",
                details={"operation_id": operation_id},
                retryable=False,
            )

        timeout = (
            self.config_manager.get("git.operation_timeout_seconds")
            if self.config_manager
            else 10
        )

        repo_path = self.snapshot_manager.find_repo_root(file_path)
        return await self.snapshot_manager.create_snapshot(
            repo_path=repo_path,
            operation_id=operation_id,
            timeout_seconds=timeout,
        )

    async def _execute_capability_placeholder(
        self, capability: str, action: str, params: Dict[str, Any], operation_id: str
    ) -> Dict[str, Any]:
        """
        Placeholder for capability execution.

        Actual capability implementations are in later stories:
        - File operations (Story 1.5-1.6)
        - Git operations (Epic 2)
        - Scheduler (Epic 4)
        - Web search (Epic 6)

        Args:
            capability: Capability module
            action: Operation action
            params: Operation parameters

        Returns:
            Placeholder result dict
        """
        logger.debug(
            "capability_execution_placeholder",
            capability=capability,
            action=action,
            note="Placeholder - actual capabilities in later stories",
        )

        return {
            "status": "placeholder",
            "message": f"Capability {capability}.{action} not yet implemented",
        }

    async def _execute_capability(
        self, capability: str, action: str, params: Dict[str, Any], operation_id: str
    ) -> Dict[str, Any]:
        """Execute capability action with concrete implementations when available."""
        if capability == "fs":
            if action == "list":
                return self.file_ops.list_files(params.get("path", "."))
            if action == "read":
                return self.file_ops.read_file(
                    path=params["path"],
                    max_size_mb=int(params.get("max_size_mb", 10)),
                )
            if action == "search":
                return await self.file_ops.search_files(
                    path=params.get("path", "."),
                    pattern=params.get("pattern", ""),
                    timeout_seconds=int(params.get("timeout_seconds", 5)),
                )
            if action == "apply_patch":
                patch_max_kb = (
                    self.config_manager.get("files.patch_max_size_kb")
                    if self.config_manager
                    else 50
                )
                return self.patch_editor.apply_patch(
                    path=params["path"],
                    patch_content=params["patch"],
                    patch_max_size_kb=patch_max_kb,
                )

        if capability == "git":
            timeout = (
                self.config_manager.get("git.operation_timeout_seconds")
                if self.config_manager
                else 30
            )
            if action == "status":
                return await git_status(
                    repo_path=params["repo_path"],
                    timeout_seconds=int(params.get("timeout_seconds", 10)),
                )
            if action == "diff":
                return await git_diff(
                    repo_path=params["repo_path"],
                    diff_type=params.get("diff_type", "working_tree"),
                    file_path=params.get("file_path"),
                    commit_refs=params.get("commit_refs"),
                    timeout_seconds=int(params.get("timeout_seconds", 30)),
                )
            if action == "checkout":
                return await git_checkout(
                    repo_path=params["repo_path"],
                    branch_name=params["branch_name"],
                    timeout_seconds=int(params.get("timeout_seconds", timeout)),
                )
            if action == "commit":
                return await git_commit(
                    repo_path=params["repo_path"],
                    message=params["message"],
                    file_paths=params.get("file_paths"),
                    timeout_seconds=int(params.get("timeout_seconds", timeout)),
                )
            if action == "list_snapshots":
                snapshots = self.snapshot_manager.list_snapshots(params["repo_path"])
                return {"snapshots": snapshots, "total_count": len(snapshots)}
            if action == "prune_snapshots":
                if "retention_days" in params and params.get("retention_days") is not None:
                    retention_days = int(params["retention_days"])
                else:
                    retention_days = int(
                        self.config_manager.get("snapshot.retention_days")
                        if self.config_manager
                        else 30
                    )
                return await self.snapshot_manager.prune_snapshots(
                    repo_path=params["repo_path"],
                    retention_days=retention_days,
                    timeout_seconds=int(params.get("timeout_seconds", 60)),
                )
            if action == "rollback":
                return await self.snapshot_manager.rollback_to_snapshot(
                    repo_path=params["repo_path"],
                    snapshot_ref=params["snapshot_ref"],
                    operation_id=operation_id,
                    timeout_seconds=timeout,
                )

        if capability == "scheduler":
            async def _resolve_job_id() -> str | None:
                if params.get("job_id"):
                    return str(params["job_id"])
                if params.get("name"):
                    job = await get_job_by_name(str(params["name"]))
                    return str(job["id"]) if job else None
                return None

            if action == "create":
                return await create_job(
                    name=params["name"],
                    cron_expr=params["cron_expr"],
                    timezone=params["timezone"],
                    action=params["action"],
                    action_params=params.get("action_params"),
                    enabled=bool(params.get("enabled", True)),
                )
            if action == "list":
                jobs = await list_jobs(enabled_only=bool(params.get("enabled_only", False)))
                return {"jobs": jobs}
            if action == "delete":
                job_id = await _resolve_job_id()
                if not job_id:
                    return {"deleted": False}
                deleted = await delete_job(job_id=job_id)
                return {"deleted": deleted, "job_id": job_id}
            if action == "disable":
                job_id = await _resolve_job_id()
                if not job_id:
                    return {"updated": False}
                updated = await disable_job(job_id=job_id)
                return {"updated": updated, "job_id": job_id, "enabled": False}
            if action == "enable":
                job_id = await _resolve_job_id()
                if not job_id:
                    return {"updated": False}
                updated = await enable_job(job_id=job_id)
                return {"updated": updated, "job_id": job_id, "enabled": True}
            if action == "edit":
                job_id = await _resolve_job_id()
                if not job_id:
                    return {"updated": False, "job": None}
                job = await edit_job(job_id=job_id, updates=params["updates"])
                return {"updated": job is not None, "job_id": job_id, "job": job}

        if capability == "web":
            if action == "search":
                return await brave_search(
                    query=params["query"],
                    mode=params.get("mode", "fresh"),
                    config_manager=self.config_manager,
                )

        if capability == "observe":
            if action == "logs":
                db_path = "data/sohnbot.db"
                if self.config_manager:
                    try:
                        db_path = str(self.config_manager.get("database.path"))
                    except (TypeError, ValueError, KeyError) as exc:
                        logger.warning("observe_logs_db_path_config_invalid", error=str(exc))
                        db_path = "data/sohnbot.db"
                    except RuntimeError as exc:
                        logger.warning("observe_logs_db_path_config_error", error=str(exc))
                        db_path = "data/sohnbot.db"
                logs = await query_operation_logs(
                    db_path=db_path,
                    hours=int(params.get("hours", 24)),
                    capability=params.get("capability"),
                    status=params.get("status"),
                    chat_id=params.get("chat_id"),
                    tier=params.get("tier"),
                    limit=int(params.get("limit", 100)),
                )
                return {"logs": logs, "count": len(logs)}

        if capability == "profiles":
            if action == "lint":
                from ..capabilities.command_profiles import execute_lint_profile
                command = (
                    self.config_manager.get("commands.lint_command")
                    if self.config_manager
                    else "pylint"
                )
                timeout = (
                    self.config_manager.get("commands.lint_timeout_seconds")
                    if self.config_manager
                    else 60
                )
                return await execute_lint_profile(
                    repo_path=params["repo_path"],
                    command=command,
                    files=params.get("files") or [],
                    timeout_seconds=int(timeout),
                )
            if action == "build":
                from ..capabilities.command_profiles import execute_build_profile
                command = (
                    self.config_manager.get("commands.build_command")
                    if self.config_manager
                    else "make"
                )
                timeout = (
                    self.config_manager.get("commands.build_timeout_seconds")
                    if self.config_manager
                    else 300
                )
                return await execute_build_profile(
                    repo_path=params["repo_path"],
                    command=command,
                    target=params.get("target") or "",
                    timeout_seconds=int(timeout),
                )
            if action == "test":
                from ..capabilities.command_profiles import execute_test_profile
                command = (
                    self.config_manager.get("commands.test_command")
                    if self.config_manager
                    else "pytest"
                )
                timeout = (
                    self.config_manager.get("commands.test_timeout_seconds")
                    if self.config_manager
                    else 600
                )
                return await execute_test_profile(
                    repo_path=params["repo_path"],
                    command=command,
                    pattern=params.get("pattern") or "",
                    timeout_seconds=int(timeout),
                )
            if action == "ripgrep":
                from ..capabilities.command_profiles import execute_ripgrep_profile
                command = (
                    self.config_manager.get("commands.ripgrep_command")
                    if self.config_manager
                    else "rg"
                )
                timeout = (
                    self.config_manager.get("commands.ripgrep_timeout_seconds")
                    if self.config_manager
                    else 30
                )
                return await execute_ripgrep_profile(
                    repo_path=params["repo_path"],
                    pattern=params["pattern"],
                    file_types=params.get("file_types") or None,
                    timeout_seconds=int(params.get("timeout_seconds") or timeout),
                    command=str(command),
                )

        return await self._execute_capability_placeholder(capability, action, params, operation_id)

    async def _execute_dry_run_preview(
        self,
        capability: str,
        action: str,
        params: Dict[str, Any],
        operation_id: str,
    ) -> Dict[str, Any]:
        """Return side-effect-free preview response for supported operations."""
        _ = operation_id
        logger.info("dry_run_preview_started", capability=capability, action=action)

        if capability == "fs" and action == "apply_patch":
            patch_content = str(params.get("patch", ""))
            hunks = [line for line in patch_content.splitlines() if line.startswith("@@")]
            return {
                "preview": True,
                "operation": "apply_patch",
                "file": params.get("path"),
                "patch": patch_content,
                "hunks_count": len(hunks),
                "message": f"🔍 DRY RUN - Would apply {len(hunks)} hunks to {params.get('path')}",
            }

        if capability == "git" and action == "commit":
            files = params.get("file_paths") or []
            return {
                "preview": True,
                "operation": "git_commit",
                "message_text": params.get("message"),
                "files": files,
                "files_count": len(files),
                "message": f"🔍 DRY RUN - Would commit {len(files)} file(s)",
            }

        if capability == "profiles":
            repo_path = params.get("repo_path", ".")
            if action == "lint":
                command = (
                    self.config_manager.get("commands.lint_command")
                    if self.config_manager
                    else "pylint"
                )
                cmd_preview = " ".join([str(command), *(params.get("files") or [])]).strip()
            elif action == "build":
                command = (
                    self.config_manager.get("commands.build_command")
                    if self.config_manager
                    else "make"
                )
                target = params.get("target") or ""
                cmd_preview = " ".join([str(command), str(target)]).strip()
            elif action == "test":
                command = (
                    self.config_manager.get("commands.test_command")
                    if self.config_manager
                    else "pytest"
                )
                pattern = params.get("pattern") or ""
                cmd_preview = " ".join([str(command), str(pattern)]).strip()
            elif action == "ripgrep":
                command = (
                    self.config_manager.get("commands.ripgrep_command")
                    if self.config_manager
                    else "rg"
                )
                file_types = params.get("file_types") or []
                type_flags: list[str] = []
                for file_type in file_types:
                    type_flags.extend(["-t", str(file_type)])
                cmd_preview = " ".join([str(command), "--json", *type_flags, str(params.get("pattern") or "")]).strip()
            else:
                cmd_preview = f"{action} (preview unavailable)"
            return {
                "preview": True,
                "operation": f"profile_{action}",
                "command": cmd_preview,
                "repo_path": repo_path,
                "message": f"🔍 DRY RUN - Would execute: {cmd_preview}",
            }

        return {
            "preview": True,
            "operation": f"{capability}_{action}",
            "params": params,
            "message": f"🔍 DRY RUN - Would execute {capability}.{action}",
        }

    async def _mark_operation_dry_run(self, operation_id: str, result: Dict[str, Any]) -> None:
        """Annotate execution_log.details with dry_run flag and preview summary."""
        db = await get_db()
        details = {"dry_run": True}
        if isinstance(result, dict):
            if "operation" in result:
                details["preview_operation"] = result.get("operation")
            if "message" in result:
                details["preview_message"] = result.get("message")
        await db.execute(
            "UPDATE execution_log SET details = ? WHERE operation_id = ?",
            (json.dumps(details), operation_id),
        )
        await db.commit()

    def _format_notification_message(
        self,
        capability: str,
        action: str,
        params: Dict[str, Any],
        status: str,
        snapshot_ref: Optional[str],
        result: Optional[Dict[str, Any]] = None,
    ) -> str:
        if capability == "profiles" and action == "lint" and status == "completed":
            data = result or {}
            passed = "✅ PASSED" if data.get("passed") else "❌ FAILED"
            exit_code = data.get("exit_code", "?")
            repo = params.get("repo_path", "-")
            return f"{passed} Lint profile | exit_code={exit_code} | repo={repo}"

        if capability == "profiles" and action == "build" and status == "completed":
            data = result or {}
            passed = "✅ PASSED" if data.get("passed") else "❌ FAILED"
            exit_code = data.get("exit_code", "?")
            repo = params.get("repo_path", "-")
            return f"{passed} Build profile | exit_code={exit_code} | repo={repo}"

        if capability == "profiles" and action == "test" and status == "completed":
            data = result or {}
            passed = "✅ PASSED" if data.get("passed") else "❌ FAILED"
            exit_code = data.get("exit_code", "?")
            repo = params.get("repo_path", "-")
            return f"{passed} Test profile | exit_code={exit_code} | repo={repo}"

        if capability == "profiles" and action == "ripgrep" and status == "completed":
            data = result or {}
            exit_code = data.get("exit_code", "?")
            repo = params.get("repo_path", "-")
            total_matches = data.get("total_matches", 0)
            return (
                f"✅ Ripgrep profile | exit_code={exit_code} | "
                f"matches={total_matches} | repo={repo}"
            )

        if capability == "web" and action == "search" and status == "completed":
            data = result or {}
            total_results = data.get("total_results", 0)
            mode = data.get("mode", params.get("mode", "fresh"))
            return f"✅ Web search | mode={mode} | results={total_results}"

        if capability == "git" and action == "commit" and status == "completed":
            data = result or {}
            commit_hash = data.get("commit_hash")
            if not commit_hash:
                return "ℹ️ No changes to commit"
            message = data.get("message", params.get("message", ""))
            files_changed = data.get("files_changed", 0)
            return f"✅ Commit created: {commit_hash}. Message: \"{message}\". Files: {files_changed}"

        emoji = "✅" if status == "completed" else ("⏱️" if status == "timeout" else "❌")
        affected = params.get("paths") or params.get("path") or params.get("repo_path") or "-"
        message = f"{emoji} {capability}.{action} | files={affected} | result={status}"
        if snapshot_ref:
            message += f" | snapshot={snapshot_ref}"
        return message

    async def _enqueue_operation_notification(
        self,
        operation_id: str,
        chat_id: str,
        capability: str,
        action: str,
        params: Dict[str, Any],
        status: str,
        snapshot_ref: Optional[str],
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Queue notification in persistent outbox without blocking operation result."""
        try:
            enabled = await get_notifications_enabled(chat_id)
            if not enabled:
                return
            message = self._format_notification_message(
                capability=capability,
                action=action,
                params=params,
                status=status,
                snapshot_ref=snapshot_ref,
                result=result,
            )
            await enqueue_notification(
                operation_id=operation_id,
                chat_id=chat_id,
                message_text=message,
            )
        except Exception as exc:
            logger.warning(
                "notification_enqueue_failed",
                operation_id=operation_id,
                chat_id=chat_id,
                capability=capability,
                action=action,
                error=str(exc),
            )
