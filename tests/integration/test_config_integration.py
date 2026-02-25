"""Integration tests for configuration system end-to-end."""

import pytest
import tempfile
from pathlib import Path
import os

from src.sohnbot.config.manager import ConfigManager, initialize_config


class TestConfigurationIntegration:
    """Integration tests for complete configuration loading workflow."""

    def test_full_config_loading_workflow(self):
        """Test complete config loading from TOML, env vars, and validation."""
        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write('''
[scope]
allowed_roots = ["~/Projects", "~/TestDir"]

[database]
path = "data/test.db"
wal_mode = true

[logging]
level = "DEBUG"
retention_days = 30

[scheduler]
tick_seconds = 120
max_concurrent_jobs = 5
''')
            temp_config = Path(f.name)

        try:
            # Initialize config manager with temp file
            manager = ConfigManager(config_file=temp_config)

            # Load static config
            static = manager.load_static_config()

            # Verify static config loaded correctly
            assert static["scope.allowed_roots"] == ["~/Projects", "~/TestDir"]
            assert static["database.path"] == "data/test.db"
            assert static["database.wal_mode"] is True

            # Load dynamic config
            dynamic = manager.load_dynamic_config_defaults()

            # Verify dynamic config loaded correctly
            assert dynamic["logging.level"] == "DEBUG"
            assert dynamic["logging.retention_days"] == 30
            assert dynamic["scheduler.tick_seconds"] == 120
            assert dynamic["scheduler.max_concurrent_jobs"] == 5

            # Verify get() method works for both tiers
            assert manager.get("scope.allowed_roots") == ["~/Projects", "~/TestDir"]
            assert manager.get("logging.level") == "DEBUG"

        finally:
            temp_config.unlink()

    def test_env_variable_override_integration(self):
        """Test environment variable overrides work end-to-end."""
        # Set env variable
        os.environ["SOHNBOT_DATABASE_PATH"] = "custom/database.db"

        try:
            manager = ConfigManager()
            static = manager.load_static_config()

            # Verify env override applied
            assert static["database.path"] == "custom/database.db"

        finally:
            del os.environ["SOHNBOT_DATABASE_PATH"]

    @pytest.mark.asyncio
    async def test_hot_reload_workflow_integration(self):
        """Test complete hot-reload workflow with subscribers."""
        manager = ConfigManager()
        manager.load_static_config()
        manager.load_dynamic_config_defaults()

        # Track notifications
        notifications = []

        def subscriber(key: str, value: any):
            notifications.append((key, value))

        # Subscribe to updates
        manager.subscribe(subscriber)

        # Update dynamic config
        await manager.update_dynamic_config("logging.level", "ERROR")

        # Verify update and notification
        assert manager.get("logging.level") == "ERROR"
        assert len(notifications) == 1
        assert notifications[0] == ("logging.level", "ERROR")

    def test_validation_enforcement_integration(self):
        """Test that validation is enforced across the system."""
        # Create temp config with invalid value
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write('''
[scheduler]
tick_seconds = 5  # Below minimum of 10
''')
            temp_config = Path(f.name)

        try:
            manager = ConfigManager(config_file=temp_config)
            manager.load_static_config()

            # Should raise validation error
            with pytest.raises(ValueError, match="below minimum"):
                manager.load_dynamic_config_defaults()

        finally:
            temp_config.unlink()

    def test_static_vs_dynamic_tier_enforcement(self):
        """Test that static/dynamic tier enforcement works."""
        manager = ConfigManager()
        manager.load_static_config()
        manager.load_dynamic_config_defaults()

        # Try to hot-update static config - should fail
        with pytest.raises(KeyError, match="Cannot hot-update static config"):
            import asyncio
            asyncio.run(manager.update_dynamic_config("database.path", "new/path.db"))

    def test_default_fallback_integration(self):
        """Test that defaults are used when config file missing."""
        # Use non-existent config file
        manager = ConfigManager(config_file=Path("nonexistent.toml"))

        # Should not raise, should use defaults
        config = manager.load_static_config()

        # Verify defaults loaded
        assert config["database.path"] == "data/sohnbot.db"
        assert config["scope.allowed_roots"] == ["~/Projects", "~/Notes"]

    @pytest.mark.asyncio
    async def test_multiple_subscribers_integration(self):
        """Test that multiple subscribers all receive notifications."""
        manager = ConfigManager()
        manager.load_static_config()
        manager.load_dynamic_config_defaults()

        # Multiple subscribers
        notifications1 = []
        notifications2 = []
        notifications3 = []

        manager.subscribe(lambda k, v: notifications1.append((k, v)))
        manager.subscribe(lambda k, v: notifications2.append((k, v)))
        manager.subscribe(lambda k, v: notifications3.append((k, v)))

        # Update config
        await manager.update_dynamic_config("scheduler.tick_seconds", 180)

        # All subscribers should be notified
        assert len(notifications1) == 1
        assert len(notifications2) == 1
        assert len(notifications3) == 1
        assert notifications1[0] == ("scheduler.tick_seconds", 180)
        assert notifications2[0] == ("scheduler.tick_seconds", 180)
        assert notifications3[0] == ("scheduler.tick_seconds", 180)


class TestGlobalConfigInstance:
    """Integration tests for global configuration instance."""

    def test_initialize_config_creates_global_instance(self):
        """Test that initialize_config creates usable global instance."""
        manager = initialize_config()

        # Verify it's initialized and loaded
        assert isinstance(manager, ConfigManager)
        assert len(manager.static_config) > 0
        assert len(manager.dynamic_config) > 0

        # Verify configs are accessible
        assert "database.path" in manager.static_config
        assert "logging.level" in manager.dynamic_config
