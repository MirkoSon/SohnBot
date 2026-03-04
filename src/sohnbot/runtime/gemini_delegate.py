"""
Gemini delegation for cost optimization.

Allows Claude (running on Haiku) to delegate complex reasoning tasks
to Gemini Pro, reducing Claude API quota usage.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class GeminiDelegateError(Exception):
    """Error during Gemini delegation."""
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


async def delegate_to_gemini(prompt: str, max_tokens: int = 8000) -> str:
    """
    Delegate complex reasoning to Gemini Pro.

    Use this for tasks that don't require file operations or SohnBot capabilities:
    - Code analysis and review
    - Long document summarization
    - Research and synthesis
    - Complex reasoning and explanations
    - Data analysis

    Args:
        prompt: Prompt to send to Gemini Pro
        max_tokens: Maximum output tokens (default: 8000)

    Returns:
        Gemini's response text

    Raises:
        GeminiDelegateError: If delegation fails
    """
    logger.info("gemini_delegation_started", prompt_length=len(prompt))

    # Check for API key (support both env var names)
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("gemini_api_key_missing")
        raise GeminiDelegateError(
            code="api_key_missing",
            message="GOOGLE_API_KEY environment variable not set",
            details={"env_var": "GOOGLE_API_KEY"}
        )

    try:
        # Import here to avoid hard dependency if not using Gemini
        import google.generativeai as genai

        # Configure API
        genai.configure(api_key=api_key)

        # Create model instance
        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": 0.7,
        }

        model_name = (os.getenv("SOHNBOT_GEMINI_MODEL") or "gemini-3-flash-preview").strip()
        model = genai.GenerativeModel(
            model_name=model_name,
            generation_config=generation_config
        )

        # Generate response
        logger.info("gemini_generation_started", model=model_name)
        response = await model.generate_content_async(prompt)

        if not response.text:
            logger.error("gemini_empty_response")
            raise GeminiDelegateError(
                code="empty_response",
                message="Gemini returned empty response",
                details={"prompt_length": len(prompt)}
            )

        logger.info(
            "gemini_delegation_completed",
            response_length=len(response.text),
            prompt_length=len(prompt)
        )

        return response.text

    except ImportError as exc:
        logger.error("gemini_sdk_not_installed", error=str(exc))
        raise GeminiDelegateError(
            code="sdk_not_installed",
            message="google-generativeai package not installed. Run: poetry add google-generativeai",
            details={"error": str(exc)}
        ) from exc

    except Exception as exc:
        logger.error(
            "gemini_delegation_failed",
            error=str(exc),
            error_type=type(exc).__name__
        )
        raise GeminiDelegateError(
            code="delegation_failed",
            message=f"Gemini delegation failed: {str(exc)}",
            details={"error_type": type(exc).__name__, "error": str(exc)}
        ) from exc
