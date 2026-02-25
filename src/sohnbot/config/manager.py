"""Configuration Manager - Two-Tier Configuration System.

This module implements the configuration management system for SohnBot, providing:
1. Static configuration loading from TOML files and environment variables
2. Dynamic configuration seeding and loading from SQLite database
3. Hot-reload event system for runtime configuration updates

Design:
- Static Config: Loaded at startup from default.toml + env overrides (restart required)
- Dynamic Config: Seeded from TOML to SQLite, authoritative source is database (hot-reloadable)
- Event System: Subscribers listen for config_updated events to apply changes
"""

import os
from pathlib import Path
from typing import Any, Optional
import asyncio
from collections.abc import Callable

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore

from dotenv import load_dotenv
import structlog

# Import registry using proper relative import
from .registry import (
    REGISTRY,
    get_config_key,
    validate_config_value,
    get_default_values,
    get_static_keys,
    get_dynamic_keys,
)

logger = structlog.get_logger()


# Secret keys that should never be logged
SENSITIVE_KEYS = {
    "anthropic_api_key",
    "telegram_bot_token",
    "brave_api_key",
}


def _redact_sensitive_value(key: str, value: Any) -> Any:
    """Redact sensitive configuration values for logging.

    Args:
        key: Configuration key
        value: Configuration value

    Returns:
        Original value if not sensitive, otherwise "[REDACTED]"
    """
    # Check if key contains any sensitive keywords
    key_lower = key.lower()
    for sensitive_key in SENSITIVE_KEYS:
        if sensitive_key in key_lower:
            return "[REDACTED]"
    return value


class ConfigManager:
    """Manages two-tier configuration system with hot-reload support.

    Attributes:
        static_config: Static configuration (restart required)
        dynamic_config: Dynamic configuration (hot-reloadable)
        _subscribers: Event subscribers for config updates
        _update_event: Asyncio event for signaling configuration changes
    """

    def __init__(self, config_file: Optional[Path] = None, env_file: Optional[Path] = None):
        """Initialize configuration manager.

        Args:
            config_file: Path to TOML config file (default: config/default.toml)
            env_file: Path to .env file (default: .env in project root)
        """
        self.static_config: dict[str, Any] = {}
        self.dynamic_config: dict[str, Any] = {}
        self._subscribers: list[Callable[[str, Any], None]] = []
        self._update_event = asyncio.Event()

        # Determine paths
        if config_file is None:
            config_file = Path("config/default.toml")
        if env_file is None:
            env_file = Path(".env")

        self.config_file = config_file
        self.env_file = env_file

        logger.info("config_manager_initialized",
                   config_file=str(config_file),
                   env_file=str(env_file))

    def load_static_config(self) -> dict[str, Any]:
        """Load static configuration from TOML and environment variables.

        Precedence: code defaults < TOML file < environment variables

        Returns:
            Dictionary of static configuration key-value pairs

        Raises:
            ValueError: If configuration validation fails

        Note:
            If config file doesn't exist, defaults are used with a warning.
            This allows the system to start with sensible defaults.
        """
        logger.info("loading_static_config", config_file=str(self.config_file))

        # Load environment variables from .env file
        if self.env_file.exists():
            load_dotenv(self.env_file)
            logger.info("env_file_loaded", env_file=str(self.env_file))

        # Step 1: Start with defaults for static keys
        static_keys = get_static_keys()
        defaults = get_default_values()
        config = {key: defaults[key] for key in static_keys}

        # Step 2: Load from TOML file
        if self.config_file.exists():
            with open(self.config_file, "rb") as f:
                toml_data = tomllib.load(f)

            # Flatten nested TOML structure (scope.allowed_roots)
            flattened = self._flatten_toml(toml_data)

            # Apply TOML values for static keys
            for key in static_keys:
                if key in flattened:
                    config[key] = flattened[key]

            logger.info("toml_config_loaded", keys_count=len(flattened))
        else:
            logger.warning("config_file_not_found",
                          config_file=str(self.config_file),
                          using_defaults=True)

        # Step 3: Apply environment variable overrides
        # Environment variables use SOHNBOT_ prefix and underscores
        # Example: SOHNBOT_DATABASE_PATH overrides database.path
        for key in static_keys:
            env_key = "SOHNBOT_" + key.replace(".", "_").upper()
            env_value = os.getenv(env_key)
            if env_value is not None:
                # Parse env value to correct type
                config_key_def = get_config_key(key)
                try:
                    parsed_value = self._parse_env_value(env_value, config_key_def.value_type)
                    config[key] = parsed_value
                    logger.info("env_override_applied", key=key, env_key=env_key)
                except ValueError as e:
                    logger.error("env_parse_error", key=key, env_key=env_key, error=str(e))
                    raise ValueError(f"Failed to parse env var {env_key}: {e}")

        # Step 4: Validate all static config values
        for key, value in config.items():
            is_valid, error_msg = validate_config_value(key, value)
            if not is_valid:
                logger.error("static_config_validation_failed", key=key, error=error_msg)
                raise ValueError(f"Static config validation failed for '{key}': {error_msg}")

        self.static_config = config
        logger.info("static_config_loaded", keys_count=len(config))
        return config

    def load_dynamic_config_defaults(self) -> dict[str, Any]:
        """Load dynamic configuration defaults from TOML (seed values).

        These values will be used to seed the SQLite database in Story 1.2.
        Once database exists, it becomes the authoritative source.

        Returns:
            Dictionary of dynamic configuration key-value pairs
        """
        logger.info("loading_dynamic_config_defaults")

        # Step 1: Start with code defaults for dynamic keys
        dynamic_keys = get_dynamic_keys()
        defaults = get_default_values()
        config = {key: defaults[key] for key in dynamic_keys}

        # Step 2: Load from TOML file (seed values)
        if self.config_file.exists():
            with open(self.config_file, "rb") as f:
                toml_data = tomllib.load(f)

            # Flatten nested TOML structure
            flattened = self._flatten_toml(toml_data)

            # Apply TOML values for dynamic keys
            for key in dynamic_keys:
                if key in flattened:
                    config[key] = flattened[key]

        # Step 3: Validate all dynamic config values
        for key, value in config.items():
            is_valid, error_msg = validate_config_value(key, value)
            if not is_valid:
                logger.error("dynamic_config_validation_failed", key=key, error=error_msg)
                raise ValueError(f"Dynamic config validation failed for '{key}': {error_msg}")

        self.dynamic_config = config
        logger.info("dynamic_config_defaults_loaded", keys_count=len(config))
        return config

    async def load_dynamic_config_from_db(self, db_path: str) -> dict[str, Any]:
        """Load dynamic configuration from SQLite database.

        This method will be implemented in Story 1.2 when the database schema is created.
        For Story 1.1, this is a placeholder that logs the intent.

        Args:
            db_path: Path to SQLite database

        Returns:
            Dictionary of dynamic configuration from database

        Note:
            Requires config table to exist (created in Story 1.2)
        """
        logger.warning("dynamic_config_from_db_not_implemented",
                      message="Database-backed dynamic config requires Story 1.2",
                      db_path=db_path)
        # For now, return the defaults loaded from TOML
        return self.dynamic_config

    async def update_dynamic_config(self, key: str, value: Any) -> None:
        """Update a dynamic configuration value and notify subscribers.

        Args:
            key: Configuration key path
            value: New value

        Raises:
            KeyError: If key is not a dynamic config key
            ValueError: If value validation fails
        """
        config_key_def = get_config_key(key)

        if config_key_def.tier != "dynamic":
            raise KeyError(f"Cannot hot-update static config key '{key}' - restart required")

        # Validate new value
        is_valid, error_msg = validate_config_value(key, value)
        if not is_valid:
            raise ValueError(f"Config validation failed for '{key}': {error_msg}")

        # Update in-memory cache
        old_value = self.dynamic_config.get(key)
        self.dynamic_config[key] = value

        # Log with redaction for sensitive values
        logger.info("dynamic_config_updated",
                   key=key,
                   old_value=_redact_sensitive_value(key, old_value),
                   new_value=_redact_sensitive_value(key, value))

        # NOTE: Database persistence not yet implemented
        # DEPENDENCY: Story 1.2 will create config table and implement persistence here
        # IMPACT: Dynamic config changes are in-memory only and lost on restart until Story 1.2
        # TODO (Story 1.2): Add database persistence with:
        #   await self._persist_to_database(key, value)

        # Notify subscribers
        await self._notify_subscribers(key, value)

    async def _notify_subscribers(self, key: str, value: Any) -> None:
        """Notify all subscribers of configuration update.

        Args:
            key: Configuration key that was updated
            value: New value
        """
        for subscriber in self._subscribers:
            try:
                # Call subscriber (can be sync or async)
                result = subscriber(key, value)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("subscriber_notification_failed",
                           key=key,
                           subscriber=subscriber.__name__,
                           error=str(e))

        # Set event to signal update
        self._update_event.set()
        self._update_event.clear()

    def subscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Subscribe to configuration update events.

        Args:
            callback: Function called when config is updated
                     Signature: (key: str, value: Any) -> None
        """
        self._subscribers.append(callback)
        logger.info("config_subscriber_added", callback=callback.__name__)

    def get(self, key: str) -> Any:
        """Get configuration value (static or dynamic).

        Args:
            key: Configuration key path

        Returns:
            Configuration value

        Raises:
            KeyError: If key not found
        """
        config_key_def = get_config_key(key)

        if config_key_def.tier == "static":
            return self.static_config.get(key, config_key_def.default)
        else:
            return self.dynamic_config.get(key, config_key_def.default)

    def _flatten_toml(self, data: dict) -> dict[str, Any]:
        """Flatten nested TOML structure to dotted keys.

        Example: {"scope": {"allowed_roots": [...]}} -> {"scope.allowed_roots": [...]}

        Args:
            data: Nested dictionary from TOML file

        Returns:
            Flattened dictionary with dotted keys
        """
        result = {}

        def _flatten(d: dict, prefix: str = ""):
            for key, value in d.items():
                full_key = f"{prefix}.{key}" if prefix else key
                if isinstance(value, dict):
                    _flatten(value, full_key)
                else:
                    result[full_key] = value

        _flatten(data)
        return result

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse environment variable string to target type.

        Args:
            value: String value from environment variable
            target_type: Target Python type

        Returns:
            Parsed value in target type

        Raises:
            ValueError: If parsing fails
        """
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        elif target_type == list:
            # Simple comma-separated list parsing
            return [item.strip() for item in value.split(",")]
        elif target_type == str:
            return value
        else:
            raise ValueError(f"Unsupported type for env parsing: {target_type}")


# Global instance (initialized in main.py)
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get global config manager instance.

    Returns:
        ConfigManager instance

    Raises:
        RuntimeError: If config manager not initialized
    """
    if _config_manager is None:
        raise RuntimeError("ConfigManager not initialized. Call initialize_config() first.")
    return _config_manager


def initialize_config(config_file: Optional[Path] = None,
                     env_file: Optional[Path] = None) -> ConfigManager:
    """Initialize global configuration manager.

    Args:
        config_file: Path to TOML config file
        env_file: Path to .env file

    Returns:
        Initialized ConfigManager instance
    """
    global _config_manager
    _config_manager = ConfigManager(config_file, env_file)
    _config_manager.load_static_config()
    _config_manager.load_dynamic_config_defaults()
    return _config_manager
