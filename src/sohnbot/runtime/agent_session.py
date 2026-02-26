"""
Claude Agent SDK Session Management.

Wrapper for ClaudeSDKClient with SohnBot-specific configuration.
"""

from pathlib import Path

import structlog
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from structlog.contextvars import bind_contextvars

from .hooks import validate_tool_use
from .mcp_tools import create_sohnbot_mcp_server

logger = structlog.get_logger(__name__)


class AgentSession:
    """Wrapper for Claude Agent SDK with SohnBot-specific configuration."""

    def __init__(self, config_manager, broker_router):
        """
        Initialize AgentSession.

        Args:
            config_manager: ConfigManager instance for config values
            broker_router: BrokerRouter instance for capability routing
        """
        self.config = config_manager
        self.broker = broker_router
        self.client = None

    async def initialize(self):
        """Initialize Claude SDK client with MCP server and hooks."""
        logger.info("initializing_agent_session")

        # Create in-process MCP server
        mcp_server = create_sohnbot_mcp_server(
            broker=self.broker,
            config=self.config
        )

        # Load model configuration
        model = self.config.get("models.telegram_default")
        max_thinking = self.config.get("runtime.telegram_max_thinking_tokens")
        max_turns = self.config.get("runtime.telegram_max_turns")

        logger.info(
            "agent_config_loaded",
            model=model,
            max_thinking_tokens=max_thinking,
            max_turns=max_turns
        )

        # Build options
        options = ClaudeAgentOptions(
            model=model,
            max_thinking_tokens=max_thinking,
            max_turns=max_turns,
            mcp_servers={"sohnbot": mcp_server},
            allowed_tools=[
                "mcp__sohnbot__fs__read",
                "mcp__sohnbot__fs__list",
                "mcp__sohnbot__fs__search",
                "mcp__sohnbot__files__read",
                "mcp__sohnbot__files__list",
                "mcp__sohnbot__files__search",
                "mcp__sohnbot__fs__apply_patch",
                "mcp__sohnbot__git__status",
                "mcp__sohnbot__git__diff",
                "mcp__sohnbot__git__commit",
                "mcp__sohnbot__git__rollback",
            ],
            hooks={
                "PreToolUse": [validate_tool_use]
            },
            setting_sources=["project"],  # Load CLAUDE.md
            cwd=str(Path.cwd())
        )

        # Initialize client
        self.client = ClaudeSDKClient(options=options)
        await self.client.__aenter__()

        logger.info("agent_session_initialized")

    async def query(self, prompt: str, chat_id: str):
        """
        Query Claude with context.

        Args:
            prompt: User prompt text
            chat_id: Telegram chat ID for context

        Yields:
            Response messages from Claude SDK

        Raises:
            RuntimeError: If client not initialized
        """
        if not self.client:
            raise RuntimeError("AgentSession not initialized. Call initialize() first.")

        # Bind chat_id to context for logging
        bind_contextvars(chat_id=chat_id)

        logger.info(
            "agent_query_start",
            chat_id=chat_id,
            prompt_length=len(prompt)
        )

        # Send query
        await self.client.query(prompt)

        # Stream response
        async for message in self.client.receive_response():
            yield message

        logger.info("agent_query_complete", chat_id=chat_id)

    async def close(self):
        """Cleanup SDK client."""
        if self.client:
            logger.info("closing_agent_session")
            await self.client.__aexit__(None, None, None)
            self.client = None
            logger.info("agent_session_closed")
