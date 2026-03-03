"""
Agent Selector with Claude-to-Gemini Failover.

Implements resilient agent selection:
- Primary: Claude Agent SDK (with MCP tools)
- Fallback: Gemini Direct (when Claude hits limits)
- Auto-recovery: Periodically checks Claude availability
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class AgentMode(Enum):
    """Current active agent mode."""
    CLAUDE = "claude"
    GEMINI_FALLBACK = "gemini_fallback"


class AgentStatus:
    """Tracks current agent status and failover state."""

    def __init__(self):
        self.current_mode = AgentMode.CLAUDE
        self.claude_last_error: str | None = None
        self.claude_last_error_time: datetime | None = None
        self.claude_failure_count = 0
        self.last_health_check: datetime | None = None
        self.quota_reset_estimate: datetime | None = None

    def mark_claude_failure(self, error: str):
        """Record Claude failure and switch to Gemini."""
        self.current_mode = AgentMode.GEMINI_FALLBACK
        self.claude_last_error = error
        self.claude_last_error_time = datetime.now()
        self.claude_failure_count += 1

        # Estimate quota reset (typically 24 hours for daily quota)
        if "rate_limit" in error.lower() or "quota" in error.lower():
            self.quota_reset_estimate = datetime.now() + timedelta(hours=24)

        logger.warning(
            "claude_failover_activated",
            error=error,
            failure_count=self.claude_failure_count,
            estimated_reset=self.quota_reset_estimate.isoformat() if self.quota_reset_estimate else None
        )

    def mark_claude_recovery(self):
        """Record successful Claude recovery."""
        previous_mode = self.current_mode
        self.current_mode = AgentMode.CLAUDE
        self.claude_last_error = None
        self.claude_failure_count = 0
        self.quota_reset_estimate = None

        if previous_mode == AgentMode.GEMINI_FALLBACK:
            logger.info("claude_recovery_successful", previous_failures=self.claude_failure_count)

    def should_check_claude_health(self) -> bool:
        """Determine if we should attempt Claude health check."""
        if self.current_mode == AgentMode.CLAUDE:
            return False  # Already using Claude

        # Check every 5 minutes when in fallback mode
        if self.last_health_check is None:
            return True

        return (datetime.now() - self.last_health_check) > timedelta(minutes=5)

    def update_health_check(self):
        """Mark that health check was performed."""
        self.last_health_check = datetime.now()

    def get_status_message(self) -> str:
        """Get human-readable status for notifications."""
        if self.current_mode == AgentMode.CLAUDE:
            return "✅ Claude Agent active (full capabilities)"

        # Fallback mode
        lines = [
            "⚠️ **Gemini Fallback Mode Active**",
            "",
            f"**Reason**: {self.claude_last_error}",
            f"**Since**: {self.claude_last_error_time.strftime('%Y-%m-%d %H:%M:%S') if self.claude_last_error_time else 'Unknown'}",
            f"**Failures**: {self.claude_failure_count}",
            "",
            "**Limited Capabilities**:",
            "- ✅ Conversations and questions",
            "- ✅ Code analysis",
            "- ❌ File operations (read/write)",
            "- ❌ Git commands",
            "- ❌ Scheduled jobs",
            "- ❌ Web search",
            "",
        ]

        if self.quota_reset_estimate:
            time_until = self.quota_reset_estimate - datetime.now()
            hours = int(time_until.total_seconds() / 3600)
            lines.append(f"**Estimated Claude Recovery**: ~{hours} hours")
        else:
            lines.append("**Estimated Claude Recovery**: Unknown")

        lines.extend([
            "",
            "💡 I'll automatically switch back when Claude is available.",
            "💡 Checking Claude health every 5 minutes."
        ])

        return "\n".join(lines)


# Global agent status (singleton)
_agent_status = AgentStatus()


def get_agent_status() -> AgentStatus:
    """Get current agent status."""
    return _agent_status


async def select_agent_for_query(
    agent_session,
    gemini_fallback_fn,
    force_mode: AgentMode | None = None
) -> tuple[AgentMode, Any]:
    """
    Select which agent to use for a query.

    Args:
        agent_session: Claude AgentSession instance
        gemini_fallback_fn: Async function to use Gemini directly
        force_mode: Optional mode override (for testing)

    Returns:
        Tuple of (selected_mode, agent_function)
    """
    status = get_agent_status()

    # Force mode for testing/override
    if force_mode:
        if force_mode == AgentMode.CLAUDE:
            return (AgentMode.CLAUDE, agent_session.query)
        else:
            return (AgentMode.GEMINI_FALLBACK, gemini_fallback_fn)

    # Health check in fallback mode
    if status.current_mode == AgentMode.GEMINI_FALLBACK:
        if status.should_check_claude_health():
            status.update_health_check()

            # Try a simple health check query to Claude
            try:
                logger.info("claude_health_check_started")

                # Simple test query with short timeout
                test_result = []
                async for msg in agent_session.query(
                    prompt="Health check: respond with OK",
                    chat_id="health_check",
                    skip_ambiguity_check=True
                ):
                    test_result.append(msg)

                # If we got here, Claude is working
                status.mark_claude_recovery()
                logger.info("claude_health_check_passed")

            except Exception as exc:
                logger.info(
                    "claude_health_check_failed",
                    error=str(exc),
                    error_type=type(exc).__name__
                )
                # Stay in fallback mode

    # Return current mode's agent
    if status.current_mode == AgentMode.CLAUDE:
        return (AgentMode.CLAUDE, agent_session.query)
    else:
        return (AgentMode.GEMINI_FALLBACK, gemini_fallback_fn)


def is_claude_rate_limit_error(error: Exception) -> bool:
    """
    Check if error indicates Claude rate limit/quota exhaustion.

    Uses specific indicators to avoid false positives.
    """
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()

    # High-confidence rate limit indicators
    high_confidence = [
        "rate_limit",
        "rate limit exceeded",
        "ratelimit",
        "429",  # HTTP 429 Too Many Requests
        "quota exceeded",
        "quota_exceeded",
        "too many requests",
        "requests per",  # "requests per minute/hour"
    ]

    # Check high-confidence indicators
    if any(indicator in error_str for indicator in high_confidence):
        return True

    # Check error type (e.g., RateLimitError)
    if "ratelimit" in error_type or "quota" in error_type:
        return True

    # Reject generic errors that could be unrelated
    # "overloaded", "capacity" alone are too vague
    return False
