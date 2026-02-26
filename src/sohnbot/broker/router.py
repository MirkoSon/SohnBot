"""Broker router - central routing and policy enforcement."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, Optional
import structlog

from ..capabilities.files import FileCapabilityError, FileOps, PatchEditor
from ..capabilities.git import GitCapabilityError, SnapshotManager
from .operation_classifier import classify_tier
from .scope_validator import ScopeValidator
from ..persistence.audit import log_operation_start, log_operation_end
from ..config.manager import ConfigManager

logger = structlog.get_logger(__name__)


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
        notifier: Optional[Callable[[str, str], Coroutine[Any, Any, None]]] = None,
    ):
        """
        Initialize broker router.

        Args:
            scope_validator: ScopeValidator instance for path validation
            config_manager: ConfigManager instance for dynamic configuration (optional for tests)
            notifier: Optional async callable(chat_id, message) for best-effort notifications
        """
        self.scope_validator = scope_validator
        self.config_manager = config_manager
        self.notifier = notifier
        self.file_ops = FileOps()
        self.patch_editor = PatchEditor()
        self.snapshot_manager = SnapshotManager()
        self._operation_start_times: Dict[str, float] = {}

    async def route_operation(
        self,
        capability: str,
        action: str,
        params: Dict[str, Any],
        chat_id: str,
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
            capability: Capability module (fs, git, sched, web, profiles)
            action: Operation action (read, patch, commit, etc.)
            params: Operation parameters
            chat_id: Telegram chat ID (user identifier)

        Returns:
            BrokerResult with operation outcome
        """
        # 1. Generate operation tracking ID
        operation_id = str(uuid.uuid4())
        self._operation_start_times[operation_id] = datetime.now().timestamp()

        # 2. Classify operation tier
        file_count = self._count_files(params)
        tier = classify_tier(capability, action, file_count)

        # 3. Validate scope (if file operation)
        if capability == "fs":
            # Validate required parameters
            if action in {"read", "list", "search", "apply_patch"} and "path" not in params:
                self._operation_start_times.pop(operation_id, None)
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
                    self._operation_start_times.pop(operation_id, None)
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
                    self._operation_start_times.pop(operation_id, None)
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
                    self._operation_start_times.pop(operation_id, None)
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
            if tier in (1, 2):
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
                result = await self._execute_capability(
                    capability, action, params
                )

            # 7. Log operation end (success)
            duration_ms = self._calculate_duration(operation_id)
            await log_operation_end(
                operation_id=operation_id,
                status="completed",
                snapshot_ref=snapshot_ref,
                duration_ms=duration_ms,
            )

            # 8. Best-effort notification (Tier 1/2 operations)
            if tier in (1, 2) and self.notifier:
                await self._send_notification(
                    chat_id=chat_id,
                    capability=capability,
                    action=action,
                    params=params,
                    result=result,
                    snapshot_ref=snapshot_ref,
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
            duration_ms = self._calculate_duration(operation_id)
            await log_operation_end(
                operation_id=operation_id,
                status="failed",
                duration_ms=duration_ms,
                error_details={"code": "timeout", "message": "Operation timed out"},
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

        except (FileCapabilityError, GitCapabilityError) as e:
            # Log operation end (capability validation/runtime error)
            duration_ms = self._calculate_duration(operation_id)
            await log_operation_end(
                operation_id=operation_id,
                status="failed",
                duration_ms=duration_ms,
                error_details=e.to_dict(),
            )
            return BrokerResult(
                allowed=False,
                operation_id=operation_id,
                tier=tier,
                error=e.to_dict(),
            )

        except Exception as e:
            # Log operation end (error)
            duration_ms = self._calculate_duration(operation_id)
            await log_operation_end(
                operation_id=operation_id,
                status="failed",
                duration_ms=duration_ms,
                error_details={"code": "execution_error", "message": str(e)},
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

    def _calculate_duration(self, operation_id: str) -> int:
        """
        Calculate operation duration in milliseconds.

        Args:
            operation_id: Operation UUID

        Returns:
            Duration in milliseconds
        """
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
            logger.warning(
                "snapshot_skipped_no_file_path",
                operation_id=operation_id,
            )
            # Fallback: return a timestamp-based ref when no file path provided
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            return f"snapshot/edit-{timestamp}-{operation_id[:8]}"

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
        self, capability: str, action: str, params: Dict[str, Any]
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
        logger.info(
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
        self, capability: str, action: str, params: Dict[str, Any]
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

        return await self._execute_capability_placeholder(capability, action, params)

    async def _send_notification(
        self,
        chat_id: str,
        capability: str,
        action: str,
        params: Dict[str, Any],
        result: Optional[Dict[str, Any]],
        snapshot_ref: Optional[str],
    ) -> None:
        """
        Send best-effort Telegram notification after a Tier 1/2 operation.

        Failures are logged but NEVER propagate to caller.
        """
        try:
            if capability == "fs" and action == "apply_patch" and result:
                file_path = result.get("path", params.get("path", "?"))
                added = result.get("lines_added", 0)
                removed = result.get("lines_removed", 0)
                snap = snapshot_ref or "none"
                message = (
                    f"✅ Patch applied to {file_path}. "
                    f"Snapshot: {snap}. Lines: +{added}/-{removed}"
                )
            else:
                message = (
                    f"✅ Operation {capability}.{action} completed."
                    + (f" Snapshot: {snapshot_ref}" if snapshot_ref else "")
                )

            await self.notifier(chat_id, message)
            logger.info(
                "notification_sent",
                chat_id=chat_id,
                action=action,
                snapshot_ref=snapshot_ref,
            )
        except Exception as exc:
            logger.warning(
                "notification_failed",
                chat_id=chat_id,
                action=action,
                error=str(exc),
            )
