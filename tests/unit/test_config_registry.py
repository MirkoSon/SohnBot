"""Unit tests for configuration registry."""

import pytest

from src.sohnbot.config.registry import (
    ConfigKey,
    REGISTRY,
    get_config_key,
    validate_config_value,
    get_default_values,
    get_static_keys,
    get_dynamic_keys,
)


class TestConfigKey:
    """Test ConfigKey dataclass."""

    def test_config_key_static_restart_required(self):
        """Static config keys should have restart_required=True."""
        key = ConfigKey(tier="static", value_type=str, default="test")
        assert key.restart_required is True

    def test_config_key_dynamic_no_restart(self):
        """Dynamic config keys should have restart_required=False."""
        key = ConfigKey(tier="dynamic", value_type=int, default=42)
        assert key.restart_required is False

    def test_config_key_with_bounds(self):
        """Config keys can have min/max value bounds."""
        key = ConfigKey(
            tier="dynamic",
            value_type=int,
            default=60,
            min_value=10,
            max_value=300
        )
        assert key.min_value == 10
        assert key.max_value == 300

    def test_config_key_with_validator(self):
        """Config keys can have custom validator functions."""
        validator = lambda v: v in ("DEBUG", "INFO", "ERROR")
        key = ConfigKey(
            tier="dynamic",
            value_type=str,
            default="INFO",
            validator=validator
        )
        assert key.validator is not None
        assert key.validator("DEBUG") is True
        assert key.validator("INVALID") is False


class TestRegistry:
    """Test configuration registry."""

    def test_registry_not_empty(self):
        """Registry should contain configuration keys."""
        assert len(REGISTRY) > 0

    def test_registry_has_required_keys(self):
        """Registry should contain essential config keys."""
        required_keys = [
            "scope.allowed_roots",
            "database.path",
            "logging.level",
            "scheduler.tick_seconds",
        ]
        for key in required_keys:
            assert key in REGISTRY

    def test_all_keys_have_valid_tiers(self):
        """All registry keys must have tier 'static' or 'dynamic'."""
        for key, config_key in REGISTRY.items():
            assert config_key.tier in ("static", "dynamic"), f"Invalid tier for {key}"

    def test_all_keys_have_defaults(self):
        """All registry keys must have default values."""
        for key, config_key in REGISTRY.items():
            assert config_key.default is not None, f"Missing default for {key}"

    def test_restart_required_matches_tier(self):
        """restart_required should match tier classification."""
        for key, config_key in REGISTRY.items():
            if config_key.tier == "static":
                assert config_key.restart_required is True, f"Static key {key} should require restart"
            else:
                assert config_key.restart_required is False, f"Dynamic key {key} should not require restart"


class TestGetConfigKey:
    """Test get_config_key function."""

    def test_get_existing_key(self):
        """Should return ConfigKey for existing keys."""
        key = get_config_key("scope.allowed_roots")
        assert isinstance(key, ConfigKey)
        assert key.tier == "static"

    def test_get_nonexistent_key_raises_error(self):
        """Should raise KeyError for non-existent keys."""
        with pytest.raises(KeyError, match="not found in registry"):
            get_config_key("nonexistent.key")


class TestValidateConfigValue:
    """Test validate_config_value function."""

    def test_validate_correct_type(self):
        """Should validate value with correct type."""
        is_valid, error = validate_config_value("logging.level", "INFO")
        assert is_valid is True
        assert error is None

    def test_validate_wrong_type(self):
        """Should reject value with wrong type."""
        is_valid, error = validate_config_value("scheduler.tick_seconds", "not_an_int")
        assert is_valid is False
        assert "Expected type int" in error

    def test_validate_below_minimum(self):
        """Should reject value below minimum."""
        is_valid, error = validate_config_value("scheduler.tick_seconds", 5)
        assert is_valid is False
        assert "below minimum" in error

    def test_validate_above_maximum(self):
        """Should reject value above maximum."""
        is_valid, error = validate_config_value("scheduler.tick_seconds", 500)
        assert is_valid is False
        assert "above maximum" in error

    def test_validate_within_range(self):
        """Should accept value within valid range."""
        is_valid, error = validate_config_value("scheduler.tick_seconds", 120)
        assert is_valid is True
        assert error is None

    def test_validate_custom_validator_pass(self):
        """Should validate with custom validator (passing case)."""
        is_valid, error = validate_config_value("logging.level", "DEBUG")
        assert is_valid is True
        assert error is None

    def test_validate_custom_validator_fail(self):
        """Should reject with custom validator (failing case)."""
        is_valid, error = validate_config_value("logging.level", "INVALID_LEVEL")
        assert is_valid is False
        assert "Custom validation failed" in error

    def test_validate_nonexistent_key(self):
        """Should reject validation for nonexistent key."""
        is_valid, error = validate_config_value("nonexistent.key", "value")
        assert is_valid is False
        assert "not found in registry" in error


class TestHelperFunctions:
    """Test helper functions."""

    def test_get_default_values(self):
        """Should return dict of all default values."""
        defaults = get_default_values()
        assert isinstance(defaults, dict)
        assert len(defaults) == len(REGISTRY)
        assert "scope.allowed_roots" in defaults
        assert "scheduler.tick_seconds" in defaults

    def test_get_static_keys(self):
        """Should return list of static config keys."""
        static = get_static_keys()
        assert isinstance(static, list)
        assert len(static) > 0
        # Verify all returned keys are actually static
        for key in static:
            assert REGISTRY[key].tier == "static"

    def test_get_dynamic_keys(self):
        """Should return list of dynamic config keys."""
        dynamic = get_dynamic_keys()
        assert isinstance(dynamic, list)
        assert len(dynamic) > 0
        # Verify all returned keys are actually dynamic
        for key in dynamic:
            assert REGISTRY[key].tier == "dynamic"

    def test_static_and_dynamic_partition(self):
        """Static and dynamic keys should partition the registry."""
        static = set(get_static_keys())
        dynamic = set(get_dynamic_keys())
        all_keys = set(REGISTRY.keys())

        # No overlap
        assert len(static & dynamic) == 0
        # Complete coverage
        assert static | dynamic == all_keys


class TestSecurityInvariants:
    """Test security-critical configuration invariants."""

    def test_observability_host_must_be_localhost(self):
        """Observability HTTP host must be localhost only."""
        key = get_config_key("observability.http_host")
        assert key.default in ("127.0.0.1", "::1")
        assert key.validator is not None

        # Should accept localhost addresses
        assert key.validator("127.0.0.1") is True
        assert key.validator("::1") is True

        # Should reject non-localhost
        assert key.validator("0.0.0.0") is False
        assert key.validator("192.168.1.1") is False

    def test_scope_roots_is_static(self):
        """Scope roots must be static (security boundary)."""
        key = get_config_key("scope.allowed_roots")
        assert key.tier == "static"
        assert key.restart_required is True

    def test_database_path_is_static(self):
        """Database path must be static (foundation)."""
        key = get_config_key("database.path")
        assert key.tier == "static"
        assert key.restart_required is True


class TestConfigurationTargetPercentages:
    """Test that hot-reload percentage targets are met."""

    def test_hot_reload_target_met(self):
        """Dynamic config should be ~80%+ of total config keys (NFR-022)."""
        total = len(REGISTRY)
        dynamic = len(get_dynamic_keys())
        static = len(get_static_keys())

        dynamic_percentage = (dynamic / total) * 100

        # NFR-022: 80% of config changes should apply without restart
        # Architecture achieves ~85% hot-reloadable
        assert dynamic_percentage >= 80, f"Dynamic config is {dynamic_percentage:.1f}%, expected >=80%"

        # Verify partition
        assert dynamic + static == total
