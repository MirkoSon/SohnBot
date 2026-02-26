"""Broker router - central routing and policy enforcement."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional
import structlog

from .operation_classifier import classify_tier
from .scope_validator import ScopeValidator
from ..persistence.audit import log_operation_start, log_operation_end

logger = structlog.get_logger(__name__)


@dataclass
class BrokerResult:
    """Result of broker policy decision and operation execution."""

    allowed: bool
    operation_id: str
    tier: Optional[int] = None
    snapshot_ref: Optional[str] = None
    error: Optional[dict] = None


class BrokerRouter:
    """Central routing and policy enforcement for all capabilities."""

    def __init__(self, scope_validator: ScopeValidator):
        """
        Initialize broker router.

        Args:
            scope_validator: ScopeValidator instance for path validation
        """
        self.scope_validator = scope_validator
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
                snapshot_ref = await self._create_snapshot(operation_id)

            # Execute capability with timeout
            # TODO: Get timeout from config (Story 1.5+)
            timeout_seconds = 300  # Default 5 minutes

            async with asyncio.timeout(timeout_seconds):
                # TODO: Route to actual capability implementations (Story 1.5+)
                # For now, this is a placeholder - capabilities not yet implemented
                result = await self._execute_capability_placeholder(
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

            return BrokerResult(
                allowed=True,
                operation_id=operation_id,
                tier=tier,
                snapshot_ref=snapshot_ref,
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

    async def _create_snapshot(self, operation_id: str) -> str:
        """
        Create git snapshot branch before execution (PLACEHOLDER).

        Actual git snapshot logic is implemented in Story 1.6.
        For Story 1.2, this returns a mock snapshot reference.

        Args:
            operation_id: Operation UUID for snapshot naming

        Returns:
            Snapshot branch reference
        """
        # TODO: Implement actual git snapshot creation (Story 1.6)
        # For now, return mock snapshot reference
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        snapshot_ref = f"snapshot/edit-{timestamp}-{operation_id[:8]}"

        logger.info(
            "snapshot_created_placeholder",
            operation_id=operation_id,
            snapshot_ref=snapshot_ref,
            note="Placeholder - actual git logic in Story 1.6",
        )

        return snapshot_ref

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
