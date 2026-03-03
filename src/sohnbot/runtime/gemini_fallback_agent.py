"""
Gemini Fallback Agent.

Standalone Gemini agent used when Claude hits rate limits.
No MCP tools - pure conversation and analysis only.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import structlog

from .agent_selector import get_agent_status

logger = structlog.get_logger(__name__)


class GeminiFallbackAgent:
    """Gemini-only agent for fallback mode (no MCP tools)."""

    def __init__(self):
        self.api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        self.model_name = "gemini-2.0-flash-exp"
        self.conversation_history: dict[str, list] = {}  # chat_id -> messages

    async def query(
        self,
        prompt: str,
        chat_id: str,
        send_message=None,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        Query Gemini in fallback mode.

        Args:
            prompt: User prompt
            chat_id: Telegram chat ID
            send_message: Telegram sender (for notifications)
            **kwargs: Ignored (for compatibility with AgentSession.query)

        Yields:
            Response text chunks
        """
        logger.info(
            "gemini_fallback_query_started",
            chat_id=chat_id,
            prompt_length=len(prompt)
        )

        # Check if we just switched to fallback mode
        status = get_agent_status()
        is_first_fallback = (
            chat_id not in self.conversation_history
            and status.current_mode.value == "gemini_fallback"
        )

        # Notify user about fallback mode on first message
        if is_first_fallback and send_message:
            await send_message(
                int(chat_id),
                status.get_status_message()
            )

        # Initialize conversation history if needed
        if chat_id not in self.conversation_history:
            self.conversation_history[chat_id] = []

        # Add system context about limited capabilities
        system_message = (
            "You are Gemini, running in fallback mode for SohnBot. "
            "Claude has hit rate limits, so you're handling requests temporarily. "
            "You do NOT have access to file operations, git commands, or other MCP tools. "
            "You can only answer questions, analyze code, and have conversations. "
            "If the user asks for file operations, politely explain that those features "
            "are unavailable in fallback mode and will return when Claude's quota resets."
        )

        try:
            # Import here to avoid hard dependency
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)

            # Create model with chat history
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_message
            )

            # Add user message to history
            self.conversation_history[chat_id].append({
                "role": "user",
                "parts": [prompt]
            })

            # Generate response with streaming
            chat = model.start_chat(history=self.conversation_history[chat_id][:-1])
            response = await chat.send_message_async(
                prompt,
                stream=True
            )

            # Collect response for history
            full_response = []

            async for chunk in response:
                if chunk.text:
                    full_response.append(chunk.text)
                    # Yield in format compatible with Claude SDK
                    yield chunk.text

            # Add assistant response to history
            self.conversation_history[chat_id].append({
                "role": "model",
                "parts": ["".join(full_response)]
            })

            logger.info(
                "gemini_fallback_query_completed",
                chat_id=chat_id,
                response_length=len("".join(full_response))
            )

        except Exception as exc:
            logger.error(
                "gemini_fallback_query_failed",
                chat_id=chat_id,
                error=str(exc),
                error_type=type(exc).__name__
            )

            error_msg = (
                f"⚠️ Gemini fallback also failed: {str(exc)}\n\n"
                "Both Claude and Gemini are currently unavailable. "
                "Please try again later."
            )
            yield error_msg

    def clear_history(self, chat_id: str):
        """Clear conversation history for a chat."""
        if chat_id in self.conversation_history:
            del self.conversation_history[chat_id]
            logger.info("gemini_fallback_history_cleared", chat_id=chat_id)


# Global fallback agent instance
_fallback_agent = None


def get_gemini_fallback_agent() -> GeminiFallbackAgent:
    """Get or create Gemini fallback agent."""
    global _fallback_agent
    if _fallback_agent is None:
        _fallback_agent = GeminiFallbackAgent()
    return _fallback_agent
