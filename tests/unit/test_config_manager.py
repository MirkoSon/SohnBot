"""Unit tests for configuration manager."""

import pytest
import asyncio
from pathlib import Path
import tempfile
import os

from src.sohnbot.config.manager import ConfigManager, initialize_config


class TestConfigManagerInitialization:
    """Test ConfigManager initialization."""

    def test_init_with_defaults(self):
        """ConfigManager should initialize with default paths."""
        manager = ConfigManager()
        assert manager.config_file == Path("config/default.toml")
        assert manager.env_file == Path(".env")
        assert manager.static_config == {}
        assert manager.dynamic_config == {}

    def test_init_with_custom_paths(self):
        """ConfigManager should accept custom file paths."""
        config_path = Path("custom/config.toml")
        env_path = Path("custom/.env")
        manager = ConfigManager(config_file=config_path, env_file=env_path)
        assert manager.config_file == config_path
        assert manager.env_file == env_path


class TestStaticConfigLoading:
    """Test static configuration loading."""

    def test_load_static_config_from_file(self):
        """Should load static config from TOML file."""
        manager = ConfigManager()
        config = manager.load_static_config()

        # Verify static config loaded
        assert isinstance(config, dict)
        assert len(config) > 0

        # Verify some known static keys
        assert "scope.allowed_roots" in config
        assert "database.path" in config
        assert "observability.http_port" in config

        # Verify stored in manager
        assert manager.static_config == config

    def test_static_config_defaults(self):
        """Static config should use defaults from registry."""
        manager = ConfigManager()
        config = manager.load_static_config()

        # Check some default values
        assert config["database.path"] == "data/sohnbot.db"
        assert config["observability.http_host"] == "127.0.0.1"

    def test_static_config_validation(self):
        """Static config loading should validate values."""
        # Create temp config with invalid value
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write('[observability]\n')
            f.write('http_host = "0.0.0.0"  # Invalid - not localhost\n')
            temp_file = Path(f.name)

        try:
            manager = ConfigManager(config_file=temp_file)
            with pytest.raises(ValueError, match="Custom validation failed"):
                manager.load_static_config()
        finally:
            temp_file.unlink()

    def test_env_variable_override(self):
        """Environment variables should override TOML values."""
        # Set env var
        os.environ["SOHNBOT_DATABASE_PATH"] = "custom/path.db"

        try:
            manager = ConfigManager()
            config = manager.load_static_config()
            assert config["database.path"] == "custom/path.db"
        finally:
            # Clean up
            del os.environ["SOHNBOT_DATABASE_PATH"]


class TestDynamicConfigLoading:
    """Test dynamic configuration loading."""

    def test_load_dynamic_config_defaults(self):
        """Should load dynamic config defaults from TOML."""
        manager = ConfigManager()
        config = manager.load_dynamic_config_defaults()

        # Verify dynamic config loaded
        assert isinstance(config, dict)
        assert len(config) > 0

        # Verify some known dynamic keys
        assert "logging.level" in config
        assert "scheduler.tick_seconds" in config
        assert "models.telegram_default" in config

        # Verify stored in manager
        assert manager.dynamic_config == config

    def test_dynamic_config_defaults_values(self):
        """Dynamic config should use defaults from registry."""
        manager = ConfigManager()
        config = manager.load_dynamic_config_defaults()

        # Check some default values
        assert config["logging.level"] == "INFO"
        assert config["scheduler.tick_seconds"] == 60
        assert config["runtime.telegram_max_turns"] == 10

    def test_dynamic_config_validation(self):
        """Dynamic config loading should validate values."""
        # Create temp config with invalid value
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write('[scheduler]\n')
            f.write('tick_seconds = 5  # Invalid - below minimum of 10\n')
            temp_file = Path(f.name)

        try:
            manager = ConfigManager(config_file=temp_file)
            manager.load_static_config()  # Load static first
            with pytest.raises(ValueError, match="below minimum"):
                manager.load_dynamic_config_defaults()
        finally:
            temp_file.unlink()


class TestConfigGet:
    """Test configuration value retrieval."""

    def test_get_static_value(self):
        """Should retrieve static config value."""
        manager = ConfigManager()
        manager.load_static_config()

        value = manager.get("database.path")
        assert value == "data/sohnbot.db"

    def test_get_dynamic_value(self):
        """Should retrieve dynamic config value."""
        manager = ConfigManager()
        manager.load_static_config()
        manager.load_dynamic_config_defaults()

        value = manager.get("logging.level")
        assert value == "INFO"

    def test_get_nonexistent_key(self):
        """Should raise KeyError for nonexistent key."""
        manager = ConfigManager()
        manager.load_static_config()

        with pytest.raises(KeyError):
            manager.get("nonexistent.key")


class TestHotReload:
    """Test hot-reload functionality."""

    @pytest.mark.asyncio
    async def test_update_dynamic_config(self):
        """Should update dynamic config value."""
        manager = ConfigManager()
        manager.load_static_config()
        manager.load_dynamic_config_defaults()

        # Update dynamic value
        await manager.update_dynamic_config("logging.level", "DEBUG")

        # Verify updated
        assert manager.dynamic_config["logging.level"] == "DEBUG"
        assert manager.get("logging.level") == "DEBUG"

    @pytest.mark.asyncio
    async def test_update_static_config_fails(self):
        """Should reject updates to static config."""
        manager = ConfigManager()
        manager.load_static_config()

        with pytest.raises(KeyError, match="Cannot hot-update static config"):
            await manager.update_dynamic_config("database.path", "new/path.db")

    @pytest.mark.asyncio
    async def test_update_with_validation_failure(self):
        """Should reject invalid values in update."""
        manager = ConfigManager()
        manager.load_static_config()
        manager.load_dynamic_config_defaults()

        with pytest.raises(ValueError, match="below minimum"):
            await manager.update_dynamic_config("scheduler.tick_seconds", 5)

    @pytest.mark.asyncio
    async def test_subscriber_notification(self):
        """Should notify subscribers on config update."""
        manager = ConfigManager()
        manager.load_static_config()
        manager.load_dynamic_config_defaults()

        # Track notifications
        notifications = []

        def subscriber(key: str, value: any):
            notifications.append((key, value))

        manager.subscribe(subscriber)

        # Update config
        await manager.update_dynamic_config("logging.level", "WARNING")

        # Verify subscriber notified
        assert len(notifications) == 1
        assert notifications[0] == ("logging.level", "WARNING")

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        """Should notify all subscribers."""
        manager = ConfigManager()
        manager.load_static_config()
        manager.load_dynamic_config_defaults()

        # Track notifications from multiple subscribers
        notifications1 = []
        notifications2 = []

        manager.subscribe(lambda k, v: notifications1.append((k, v)))
        manager.subscribe(lambda k, v: notifications2.append((k, v)))

        # Update config
        await manager.update_dynamic_config("logging.level", "ERROR")

        # Verify all subscribers notified
        assert len(notifications1) == 1
        assert len(notifications2) == 1
        assert notifications1[0] == ("logging.level", "ERROR")
        assert notifications2[0] == ("logging.level", "ERROR")


class TestGlobalInstance:
    """Test global config manager instance."""

    def test_initialize_config(self):
        """Should initialize global config manager."""
        manager = initialize_config()
        assert isinstance(manager, ConfigManager)
        assert len(manager.static_config) > 0
        assert len(manager.dynamic_config) > 0


class TestTOMLFlattening:
    """Test TOML structure flattening."""

    def test_flatten_nested_structure(self):
        """Should flatten nested TOML to dotted keys."""
        manager = ConfigManager()

        nested = {
            "scope": {
                "allowed_roots": ["~/Projects"],
            },
            "database": {
                "path": "data/test.db",
            },
        }

        flattened = manager._flatten_toml(nested)

        assert flattened == {
            "scope.allowed_roots": ["~/Projects"],
            "database.path": "data/test.db",
        }

    def test_flatten_deeply_nested(self):
        """Should handle deeply nested structures."""
        manager = ConfigManager()

        nested = {
            "a": {
                "b": {
                    "c": "value"
                }
            }
        }

        flattened = manager._flatten_toml(nested)
        assert flattened == {"a.b.c": "value"}


class TestEnvParsing:
    """Test environment variable parsing."""

    def test_parse_string(self):
        """Should parse string values."""
        manager = ConfigManager()
        assert manager._parse_env_value("test", str) == "test"

    def test_parse_int(self):
        """Should parse integer values."""
        manager = ConfigManager()
        assert manager._parse_env_value("42", int) == 42

    def test_parse_float(self):
        """Should parse float values."""
        manager = ConfigManager()
        assert manager._parse_env_value("3.14", float) == 3.14

    def test_parse_bool_true(self):
        """Should parse boolean true values."""
        manager = ConfigManager()
        assert manager._parse_env_value("true", bool) is True
        assert manager._parse_env_value("1", bool) is True
        assert manager._parse_env_value("yes", bool) is True

    def test_parse_bool_false(self):
        """Should parse boolean false values."""
        manager = ConfigManager()
        assert manager._parse_env_value("false", bool) is False
        assert manager._parse_env_value("0", bool) is False
        assert manager._parse_env_value("no", bool) is False

    def test_parse_list(self):
        """Should parse comma-separated lists."""
        manager = ConfigManager()
        result = manager._parse_env_value("a,b,c", list)
        assert result == ["a", "b", "c"]

    def test_parse_list_with_spaces(self):
        """Should trim whitespace in list parsing."""
        manager = ConfigManager()
        result = manager._parse_env_value("a, b , c", list)
        assert result == ["a", "b", "c"]
