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

    async def route_to_runtime(self, chat_id: str, message: str, send_message=None) -> str:
        """
        Route message to agent runtime and return aggregated response.

        Args:
            chat_id: Telegram chat ID for context
            message: User message text
            send_message: Optional Telegram sender callback

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
                        async for msg in self.agent_session.query(
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

            # Query Claude Agent SDK (async iteration)
            async for msg in self.agent_session.query(
                prompt=message,
                chat_id=chat_id,
                send_message=send_message,
            ):
                # Aggregate AssistantMessage text blocks
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
            logger.error(
                "runtime_routing_error",
                chat_id=chat_id,
                error=str(e),
                error_type=type(e).__name__
            )
            raise
