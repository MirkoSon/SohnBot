"""
Gemini Adapter MCP server.

This adapter exposes Claude-safe MCP tool schemas and routes execution to
SohnBot's direct Gemini delegate. It avoids schema incompatibilities seen with
some third-party Gemini MCP servers.
"""

from __future__ import annotations

import os

import structlog
from claude_agent_sdk import create_sdk_mcp_server, tool
from structlog.contextvars import get_contextvars

from .gemini_delegate import GeminiDelegateError, delegate_to_gemini

logger = structlog.get_logger(__name__)

_DEFAULT_MODEL = "gemini-3-flash-preview"


def create_gemini_adapter_mcp_server():
    """Create an in-process MCP server that proxies Gemini via direct API."""

    def _as_mcp_text(text: str) -> dict:
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "generate",
        "Generate text with Gemini via SohnBot adapter",
        {"prompt": str, "max_tokens": int, "model": str},
    )
    async def generate(args):
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return _as_mcp_text("❌ Error: prompt cannot be empty")

        max_tokens = args.get("max_tokens", 4000)
        try:
            max_tokens = int(max_tokens)
        except (TypeError, ValueError):
            return _as_mcp_text("❌ Error: max_tokens must be an integer")

        if max_tokens < 100 or max_tokens > 32000:
            return _as_mcp_text("❌ Error: max_tokens must be between 100 and 32000")

        # Model selection is accepted for compatibility/future expansion.
        model = str(args.get("model") or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
        os.environ["SOHNBOT_GEMINI_MODEL"] = model

        logger.info(
            "gemini_adapter_generate_invoked",
            chat_id=chat_id,
            prompt_length=len(prompt),
            max_tokens=max_tokens,
            model=model,
        )

        try:
            response = await delegate_to_gemini(prompt=prompt, max_tokens=max_tokens)
            return _as_mcp_text(response)
        except GeminiDelegateError as exc:
            logger.warning(
                "gemini_adapter_generate_failed",
                chat_id=chat_id,
                code=exc.code,
                error=exc.message,
            )
            return _as_mcp_text(f"❌ Gemini request failed ({exc.code}): {exc.message}")
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "gemini_adapter_generate_unexpected_error",
                chat_id=chat_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return _as_mcp_text(f"❌ Gemini request failed: {exc}")

    return create_sdk_mcp_server(
        name="gemini_adapter",
        version="0.1.0",
        tools=[generate],
    )
