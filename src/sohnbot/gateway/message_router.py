"""
Message Router for Telegram Gateway.

Routes Telegram messages to Claude Agent SDK runtime and aggregates responses.
"""

import structlog

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

    async def route_to_runtime(self, chat_id: str, message: str) -> str:
        """
        Route message to agent runtime and return aggregated response.

        Args:
            chat_id: Telegram chat ID for context
            message: User message text

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

        response_parts = []

        try:
            # Query Claude Agent SDK (async iteration)
            async for msg in self.agent_session.query(
                prompt=message,
                chat_id=chat_id
            ):
                # Aggregate AssistantMessage text blocks
                if hasattr(msg, 'content'):
                    for block in msg.content:
                        if hasattr(block, 'text'):
                            response_parts.append(block.text)

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
            logger.error(
                "runtime_routing_error",
                chat_id=chat_id,
                error=str(e),
                error_type=type(e).__name__
            )
            raise
