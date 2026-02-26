"""
Context loading utilities for Claude Agent SDK.

Loads CLAUDE.md and model configuration.
"""

from pathlib import Path


def load_claude_md(project_root: Path) -> str:
    """
    Load CLAUDE.md if it exists.

    Args:
        project_root: Path to project root directory

    Returns:
        Contents of CLAUDE.md or empty string if not found
    """
    claude_md = project_root / "CLAUDE.md"
    if claude_md.exists():
        return claude_md.read_text()
    return ""


def get_model_config(config_manager) -> dict:
    """
    Get model configuration from config manager.

    Args:
        config_manager: ConfigManager instance

    Returns:
        Dict with model, max_thinking_tokens, max_turns
    """
    return {
        "model": config_manager.get("models.telegram_default"),
        "max_thinking_tokens": config_manager.get("models.telegram_max_thinking_tokens"),
        "max_turns": config_manager.get("models.telegram_max_turns"),
    }
