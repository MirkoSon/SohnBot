"""Tests for pattern validation in broker router."""

import pytest
from pathlib import Path

from src.sohnbot.broker.router import BrokerRouter
from src.sohnbot.broker.scope_validator import ScopeValidator
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager
from scripts.migrate import apply_migrations


@pytest.fixture
async def setup_database(tmp_path):
    """Set up test database with required schema."""
    db_path = tmp_path / "test.db"
    migrations_dir = (
        Path(__file__).parent.parent.parent
        / "src"
        / "sohnbot"
        / "persistence"
        / "migrations"
    )

    apply_migrations(db_path, migrations_dir)
    db_manager = DatabaseManager(db_path)
    set_db_manager(db_manager)

    yield db_manager

    await db_manager.close()


@pytest.fixture
def temp_allowed_root(tmp_path):
    """Create temporary allowed root directory."""
    projects = tmp_path / "Projects"
    projects.mkdir()
    return str(projects)


@pytest.fixture
def scope_validator(temp_allowed_root):
    """Create ScopeValidator with temp root."""
    return ScopeValidator(allowed_roots=[temp_allowed_root])


@pytest.fixture
def broker(scope_validator):
    """Create BrokerRouter with scope validator (no config manager for tests)."""
    return BrokerRouter(scope_validator=scope_validator)


class TestPatternValidation:
    """Test broker validates search pattern parameter."""

    @pytest.mark.asyncio
    async def test_search_missing_pattern_rejected(self, broker, temp_allowed_root, setup_database):
        """Search operation without pattern parameter is rejected."""
        result = await broker.route_operation(
            capability="fs",
            action="search",
            params={"path": temp_allowed_root},
            chat_id="test_user"
        )

        assert result.allowed is False
        assert result.error is not None
        assert result.error["code"] == "invalid_request"
        assert "pattern" in result.error["message"].lower()

    @pytest.mark.asyncio
    async def test_search_empty_pattern_rejected(self, broker, temp_allowed_root, setup_database):
        """Search operation with empty pattern is rejected."""
        result = await broker.route_operation(
            capability="fs",
            action="search",
            params={"path": temp_allowed_root, "pattern": ""},
            chat_id="test_user"
        )

        assert result.allowed is False
        assert result.error is not None
        assert result.error["code"] == "invalid_request"
        assert "pattern" in result.error["message"].lower()

    @pytest.mark.asyncio
    async def test_search_non_string_pattern_rejected(self, broker, temp_allowed_root, setup_database):
        """Search operation with non-string pattern is rejected."""
        result = await broker.route_operation(
            capability="fs",
            action="search",
            params={"path": temp_allowed_root, "pattern": 123},
            chat_id="test_user"
        )

        assert result.allowed is False
        assert result.error is not None
        assert result.error["code"] == "invalid_request"
        assert "pattern" in result.error["message"].lower()

    @pytest.mark.asyncio
    async def test_search_valid_pattern_passes_validation(self, broker, temp_allowed_root, setup_database):
        """Search operation with valid pattern passes broker validation."""
        result = await broker.route_operation(
            capability="fs",
            action="search",
            params={"path": temp_allowed_root, "pattern": "test"},
            chat_id="test_user"
        )

        # Will still fail because ripgrep isn't installed, but broker validation passed
        # If broker validation failed, we'd get invalid_request, not rg_not_found
        if not result.allowed:
            # Expected: ripgrep missing, not broker validation failure
            assert result.error["code"] in ("rg_not_found", "search_error")
        else:
            # If ripgrep is installed, operation succeeded
            assert result.allowed is True
