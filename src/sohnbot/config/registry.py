"""Configuration Registry - Defines all configuration keys with tier classification.

This module provides the ConfigKey dataclass and REGISTRY dictionary that defines
all configuration options available in SohnBot.

Two-Tier System:
- Static Config (tier="static"): Requires restart to apply changes
  Examples: scope roots, database path, API key names, log paths
- Dynamic Config (tier="dynamic"): Can be hot-reloaded without restart
  Examples: thresholds, timeouts, retention periods, model settings
"""

from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional


@dataclass
class ConfigKey:
    """Defines a single configuration key with validation and tier classification.

    Attributes:
        tier: "static" (restart required) or "dynamic" (hot-reloadable)
        value_type: Expected Python type (str, int, float, bool, list, dict)
        default: Default value if not specified in config files
        min_value: Minimum value for numeric types (optional)
        max_value: Maximum value for numeric types (optional)
        restart_required: Auto-derived from tier (True for static, False for dynamic)
        validator: Custom validation function (optional)
    """
    tier: Literal["static", "dynamic"]
    value_type: type
    default: Any
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    restart_required: bool = False
    validator: Optional[Callable[[Any], bool]] = None

    def __post_init__(self):
        """Auto-derive restart_required from tier."""
        self.restart_required = (self.tier == "static")


# Configuration Registry
# =======================
# All configuration keys must be registered here with their tier classification.

REGISTRY: dict[str, ConfigKey] = {
    # ===== SCOPE & SAFETY (Static - Security Boundary) =====
    "scope.allowed_roots": ConfigKey(
        tier="static",
        value_type=list,
        default=["~/Projects", "~/Notes"],
    ),

    # ===== DATABASE (Static - Foundation) =====
    "database.path": ConfigKey(
        tier="static",
        value_type=str,
        default="data/sohnbot.db",
    ),
    "database.wal_mode": ConfigKey(
        tier="static",
        value_type=bool,
        default=True,
    ),

    # ===== LOGGING (Static file path, Dynamic verbosity) =====
    "logging.file_path": ConfigKey(
        tier="static",
        value_type=str,
        default="data/sohnbot.log",
    ),
    "logging.level": ConfigKey(
        tier="dynamic",
        value_type=str,
        default="INFO",
        validator=lambda v: v in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    ),
    "logging.retention_days": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=90,
        min_value=1,
        max_value=365,
    ),

    # ===== TELEGRAM (Static for auth, Dynamic for settings) =====
    "telegram.allowed_chat_ids": ConfigKey(
        tier="static",
        value_type=list,
        default=[],
    ),
    "telegram.response_timeout_seconds": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=30,
        min_value=5,
        max_value=300,
    ),

    # ===== FILE OPERATIONS (Dynamic - Performance tuning) =====
    "files.max_size_mb": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=10,
        min_value=1,
        max_value=100,
    ),
    "files.patch_max_size_kb": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=50,
        min_value=1,
        max_value=500,
    ),
    "files.search_timeout_seconds": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=5,
        min_value=1,
        max_value=60,
    ),

    # ===== GIT OPERATIONS (Dynamic - Performance tuning) =====
    "git.snapshot_retention_days": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=30,
        min_value=1,
        max_value=90,
    ),
    "git.operation_timeout_seconds": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=10,
        min_value=1,
        max_value=60,
    ),

    # ===== SCHEDULER (Dynamic - Operational tuning) =====
    "scheduler.tick_seconds": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=60,
        min_value=10,
        max_value=300,
    ),
    "scheduler.max_concurrent_jobs": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=3,
        min_value=1,
        max_value=10,
    ),
    "scheduler.job_timeout_seconds": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=600,
        min_value=60,
        max_value=3600,
    ),

    # ===== COMMAND PROFILES (Dynamic - Timeout tuning) =====
    "commands.lint_timeout_seconds": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=60,
        min_value=10,
        max_value=300,
    ),
    "commands.build_timeout_seconds": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=300,
        min_value=60,
        max_value=1800,
    ),
    "commands.test_timeout_seconds": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=600,
        min_value=60,
        max_value=3600,
    ),
    "commands.max_chain_length": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=5,
        min_value=1,
        max_value=10,
    ),

    # ===== WEB SEARCH (Dynamic - Operational tuning) =====
    "search.cache_retention_days": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=7,
        min_value=1,
        max_value=30,
    ),
    "search.volume_alert_threshold": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=100,
        min_value=10,
        max_value=1000,
    ),

    # ===== OBSERVABILITY (Static binding, Dynamic settings) =====
    "observability.http_enabled": ConfigKey(
        tier="dynamic",
        value_type=bool,
        default=True,
    ),
    "observability.http_port": ConfigKey(
        tier="static",
        value_type=int,
        default=8080,
        min_value=1024,
        max_value=65535,
    ),
    "observability.http_host": ConfigKey(
        tier="static",
        value_type=str,
        default="127.0.0.1",
        validator=lambda v: v in ("127.0.0.1", "::1"),  # Localhost only
    ),
    "observability.refresh_seconds": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=5,
        min_value=1,
        max_value=60,
    ),

    # ===== MODEL ROUTING (Dynamic - Operational flexibility) =====
    "models.telegram_default": ConfigKey(
        tier="dynamic",
        value_type=str,
        default="claude-haiku-4-5-20251001",
        validator=lambda v: v.startswith("claude-"),
    ),
    "models.dev_default": ConfigKey(
        tier="dynamic",
        value_type=str,
        default="claude-sonnet-4-6",
        validator=lambda v: v.startswith("claude-"),
    ),
    "models.plan_default": ConfigKey(
        tier="dynamic",
        value_type=str,
        default="claude-opus-4-6",
        validator=lambda v: v.startswith("claude-"),
    ),

    # ===== RUNTIME CONTROLS (Dynamic - Budget governance) =====
    "runtime.telegram_max_thinking_tokens": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=4000,
        min_value=1000,
        max_value=32000,
    ),
    "runtime.dev_max_thinking_tokens": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=8000,
        min_value=1000,
        max_value=32000,
    ),
    "runtime.plan_max_thinking_tokens": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=16000,
        min_value=1000,
        max_value=32000,
    ),
    "runtime.telegram_max_turns": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=10,
        min_value=1,
        max_value=100,
    ),
    "runtime.dev_max_turns": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=25,
        min_value=1,
        max_value=100,
    ),
    "runtime.plan_max_turns": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=50,
        min_value=1,
        max_value=100,
    ),
    "runtime.plan_max_budget_usd": ConfigKey(
        tier="dynamic",
        value_type=float,
        default=5.00,
        min_value=0.10,
        max_value=100.00,
    ),
}


def get_config_key(key: str) -> ConfigKey:
    """Get configuration key definition from registry.

    Args:
        key: Configuration key path (e.g., "scope.allowed_roots")

    Returns:
        ConfigKey definition

    Raises:
        KeyError: If key not found in registry
    """
    if key not in REGISTRY:
        raise KeyError(f"Configuration key '{key}' not found in registry")
    return REGISTRY[key]


def validate_config_value(key: str, value: Any) -> tuple[bool, Optional[str]]:
    """Validate a configuration value against its registered definition.

    Args:
        key: Configuration key path
        value: Value to validate

    Returns:
        Tuple of (is_valid, error_message)
        error_message is None if valid
    """
    try:
        config_key = get_config_key(key)
    except KeyError as e:
        return False, str(e)

    # Type validation
    if not isinstance(value, config_key.value_type):
        return False, f"Expected type {config_key.value_type.__name__}, got {type(value).__name__}"

    # Range validation for numeric types
    if isinstance(value, (int, float)):
        if config_key.min_value is not None and value < config_key.min_value:
            return False, f"Value {value} below minimum {config_key.min_value}"
        if config_key.max_value is not None and value > config_key.max_value:
            return False, f"Value {value} above maximum {config_key.max_value}"

    # Custom validator
    if config_key.validator is not None:
        try:
            if not config_key.validator(value):
                return False, f"Custom validation failed for value: {value}"
        except Exception as e:
            return False, f"Validator error: {str(e)}"

    return True, None


def get_default_values() -> dict[str, Any]:
    """Get default values for all configuration keys.

    Returns:
        Dictionary of key -> default_value
    """
    return {key: config_key.default for key, config_key in REGISTRY.items()}


def get_static_keys() -> list[str]:
    """Get list of all static configuration keys (restart required).

    Returns:
        List of static config key paths
    """
    return [key for key, config_key in REGISTRY.items() if config_key.tier == "static"]


def get_dynamic_keys() -> list[str]:
    """Get list of all dynamic configuration keys (hot-reloadable).

    Returns:
        List of dynamic config key paths
    """
    return [key for key, config_key in REGISTRY.items() if config_key.tier == "dynamic"]
