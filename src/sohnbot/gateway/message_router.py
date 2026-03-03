"""
Message Router for Telegram Gateway.

Routes Telegram messages to Claude Agent SDK runtime and aggregates responses.
Includes failover to Gemini when Claude hits rate limits.
"""

import structlog
from structlog.contextvars import bind_contextvars

from ..runtime.agent_selector import (
    get_agent_status,
    is_claude_rate_limit_error,
    select_agent_for_query,
    AgentMode,
)
from ..runtime.gemini_fallback_agent import get_gemini_fallback_agent

logger = structlog.get_logger(__name__)


class MessageRouter:
    """Route Telegram messages to Claude Agent SDK runtime."""

    def __init__(self, agent_session):
        """
        Initialize MessageRouter.

        Args:
            agent_session: AgentSession instance for Claude SDK queries
        """
        self.agent_session = agent_session

    async def route_to_runtime(
        self,
        chat_id: str,
        message: str,
        send_message=None,
        correlation_id: str | None = None,
    ) -> str:
        """
        Route message to agent runtime and return aggregated response.

        Args:
            chat_id: Telegram chat ID for context
            message: User message text
            send_message: Optional Telegram sender callback
            correlation_id: Optional request correlation identifier

        Returns:
            Aggregated response text from Claude

        Raises:
            Exception: If agent runtime fails
        """
        logger.info(
            "routing_to_runtime",
            chat_id=chat_id,
            message_length=len(message)
        )

        if correlation_id:
            bind_contextvars(correlation_id=correlation_id)

        response_parts = []

        try:
            # Select agent (Claude or Gemini fallback)
            gemini_fallback = get_gemini_fallback_agent()
            selected_mode, agent_query = await select_agent_for_query(
                agent_session=self.agent_session,
                gemini_fallback_fn=gemini_fallback.query
            )

            logger.info(
                "agent_selected",
                mode=selected_mode.value,
                chat_id=chat_id
            )

            # Postponement only works with Claude (requires MCP tools)
            if selected_mode == AgentMode.CLAUDE:
                if await self.agent_session.postponement_manager.has_pending(chat_id):
                    pending = await self.agent_session.postponement_manager.resolve(
                        chat_id=chat_id,
                        response_text=message,
                    )
                    if pending and pending.postponed and pending.response_text:
                        completed = await self.agent_session.postponement_manager.consume_resolved(chat_id)
                        if completed:
                            clarified_prompt = self.agent_session.postponement_manager.build_clarified_prompt(
                                original_prompt=completed.original_prompt,
                                clarification_response=completed.response_text,
                            )
                            async for msg in agent_query(
                                prompt=clarified_prompt,
                                chat_id=chat_id,
                                send_message=send_message,
                                skip_ambiguity_check=True,
                            ):
                                if hasattr(msg, "content"):
                                    for block in msg.content:
                                        if hasattr(block, "text"):
                                            response_parts.append(block.text)
                                elif isinstance(msg, str):
                                    response_parts.append(msg)
                            return "\n\n".join(response_parts)
                    # For non-postponed pending requests, the original in-flight query
                    # will continue and respond. Avoid sending duplicate acknowledgement.
                    return ""

            # Query selected agent (async iteration)
            async for msg in agent_query(
                prompt=message,
                chat_id=chat_id,
                send_message=send_message,
            ):
                # Aggregate response (Claude returns AssistantMessage, Gemini returns str)
                if hasattr(msg, 'content'):
                    for block in msg.content:
                        if hasattr(block, 'text'):
                            response_parts.append(block.text)
                elif isinstance(msg, str):
                    response_parts.append(msg)

            aggregated_response = "\n\n".join(response_parts)

            # Guard against empty responses
            if not aggregated_response.strip():
                logger.warning(
                    "empty_response_from_runtime",
                    chat_id=chat_id,
                    parts_count=len(response_parts)
                )
                return "⚠️ No response generated. Please try again or rephrase your message."

            logger.info(
                "runtime_response_received",
                chat_id=chat_id,
                response_length=len(aggregated_response)
            )

            return aggregated_response

        except Exception as e:
            # Check if this is a Claude rate limit error
            if is_claude_rate_limit_error(e):
                logger.warning(
                    "claude_rate_limit_detected",
                    chat_id=chat_id,
                    error=str(e),
                    error_type=type(e).__name__
                )

                # Mark failover to Gemini
                status = get_agent_status()
                status.mark_claude_failure(str(e))

                # Notify user and retry with Gemini
                if send_message:
                    await send_message(
                        int(chat_id),
                        "⚠️ **Claude Rate Limit Reached**\n\n"
                        "Switching to Gemini fallback mode...\n\n"
                        f"{status.get_status_message()}"
                    )

                # Retry with Gemini fallback
                try:
                    logger.info("retrying_with_gemini_fallback", chat_id=chat_id)

                    gemini_fallback = get_gemini_fallback_agent()
                    response_parts = []

                    async for msg in gemini_fallback.query(
                        prompt=message,
                        chat_id=chat_id,
                        send_message=send_message,
                    ):
                        if isinstance(msg, str):
                            response_parts.append(msg)

                    return "\n\n".join(response_parts) if response_parts else "⚠️ Fallback also failed. Please try again later."

                except Exception as fallback_error:
                    logger.error(
                        "gemini_fallback_also_failed",
                        chat_id=chat_id,
                        error=str(fallback_error),
                        error_type=type(fallback_error).__name__
                    )
                    # Sanitize error messages for users (full details in logs)
                    return (
                        "❌ **Both AI providers are currently unavailable**\n\n"
                        "- Primary agent: Rate limit reached\n"
                        "- Fallback agent: Also unavailable\n\n"
                        "This is usually temporary. Please try again in a few minutes.\n"
                        "Check `/logs` for details."
                    )

            # Other errors - re-raise
            logger.error(
                "runtime_routing_error",
                chat_id=chat_id,
                error=str(e),
                error_type=type(e).__name__
            )
            raise
