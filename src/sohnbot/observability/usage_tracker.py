"""
Track Claude and Gemini API usage for cost monitoring.

Logs token usage to help users understand and optimize their API costs.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# Approximate pricing per 1M tokens (USD) - Update based on current pricing
# Source: https://www.anthropic.com/pricing and https://ai.google.dev/pricing
PRICING = {
    "claude-haiku-4-5": {"input": 0.25, "output": 1.25, "cache_write": 0.30, "cache_read": 0.03},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},  # Per 1M tokens
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}


async def log_claude_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    thinking_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    operation: str | None = None,
) -> None:
    """
    Log Claude API usage with cost estimation.

    Args:
        model: Claude model name (e.g., "claude-sonnet-4-6")
        input_tokens: Input token count
        output_tokens: Output token count
        thinking_tokens: Extended thinking token count
        cache_creation_tokens: Prompt cache creation tokens
        cache_read_tokens: Prompt cache read tokens
        operation: Optional operation description
    """
    # Normalize model name to pricing key
    model_key = "-".join(model.split("-")[:3])  # e.g., "claude-sonnet-4-6"

    if model_key not in PRICING:
        logger.warning(
            "unknown_model_pricing",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )
        return

    pricing = PRICING[model_key]

    # Calculate costs (tokens / 1M * price per 1M)
    cost_input = (input_tokens / 1_000_000) * pricing["input"]
    cost_output = (output_tokens / 1_000_000) * pricing["output"]
    cost_cache_write = (cache_creation_tokens / 1_000_000) * pricing.get("cache_write", 0)
    cost_cache_read = (cache_read_tokens / 1_000_000) * pricing.get("cache_read", 0)

    total_cost = cost_input + cost_output + cost_cache_write + cost_cache_read
    total_tokens = input_tokens + output_tokens + thinking_tokens

    logger.info(
        "claude_usage",
        model=model,
        operation=operation,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thinking_tokens=thinking_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=round(total_cost, 6),
        cost_breakdown={
            "input": round(cost_input, 6),
            "output": round(cost_output, 6),
            "cache_write": round(cost_cache_write, 6),
            "cache_read": round(cost_cache_read, 6),
        }
    )


async def log_gemini_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    operation: str | None = None,
) -> None:
    """
    Log Gemini API usage with cost estimation.

    Args:
        model: Gemini model name (e.g., "gemini-2.0-flash-exp")
        input_tokens: Input token count
        output_tokens: Output token count
        operation: Optional operation description
    """
    # Normalize model name to pricing key
    model_key = "-".join(model.split("-")[:3])  # e.g., "gemini-2.0-flash"

    if model_key not in PRICING:
        # Use default flash pricing for unknown models
        model_key = "gemini-2.0-flash"
        logger.warning(
            "unknown_gemini_model_pricing",
            model=model,
            fallback=model_key
        )

    pricing = PRICING[model_key]

    # Calculate costs
    cost_input = (input_tokens / 1_000_000) * pricing["input"]
    cost_output = (output_tokens / 1_000_000) * pricing["output"]
    total_cost = cost_input + cost_output
    total_tokens = input_tokens + output_tokens

    logger.info(
        "gemini_usage",
        model=model,
        operation=operation,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=round(total_cost, 6),
        cost_breakdown={
            "input": round(cost_input, 6),
            "output": round(cost_output, 6),
        }
    )


def get_cost_estimate(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """
    Get quick cost estimate for a model and token count.

    Args:
        model: Model name
        input_tokens: Input token count
        output_tokens: Output token count

    Returns:
        Estimated cost in USD
    """
    model_key = "-".join(model.split("-")[:3])

    if model_key not in PRICING:
        return 0.0

    pricing = PRICING[model_key]
    cost_input = (input_tokens / 1_000_000) * pricing["input"]
    cost_output = (output_tokens / 1_000_000) * pricing["output"]

    return cost_input + cost_output
