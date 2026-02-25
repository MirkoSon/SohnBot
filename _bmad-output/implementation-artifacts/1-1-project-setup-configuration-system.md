# Story 1.1: Project Setup & Configuration System

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a developer,
I want a complete project structure with configuration management,
So that I can deploy SohnBot with proper environment setup and dynamic configuration.

## Acceptance Criteria

**Given** the Poetry project is initialized with Python 3.13+
**When** I run the setup script
**Then** all directory structure is created (broker, capabilities, gateway, runtime, config, persistence, supervision)
**And** default configuration is loaded from config/default.toml
**And** environment variables are loaded from .env file
**And** configuration registry validates all config keys
**And** hot-reload is supported for dynamic config keys

## Tasks / Subtasks

- [x] Initialize Poetry project with Python 3.13+ (AC: 1)
  - [x] Create pyproject.toml with all initial dependencies
  - [x] Configure build system and metadata
  - [x] Set up development dependencies (pytest, etc.)

- [x] Create complete directory structure (AC: 2)
  - [x] Create src/sohnbot/ with all 7 subsystems
  - [x] Create gateway/ (Telegram interface)
  - [x] Create runtime/ (Claude Agent SDK)
  - [x] Create broker/ (policy enforcement heart)
  - [x] Create capabilities/ (files, git, command_profiles, search, scheduler)
  - [x] Create persistence/ (SQLite management)
  - [x] Create supervision/ (health monitoring)
  - [x] Create config/ (configuration management)
  - [x] Create all __init__.py files
  - [x] Create tests/, config/, scripts/, docs/ directories

- [x] Implement two-tier configuration system (AC: 3, 4, 5)
  - [x] Create config/registry.py with ConfigKey definitions
  - [x] Create config/default.toml with seed values
  - [x] Create src/sohnbot/config/manager.py with hot-reload event system
  - [x] Implement static config loading (TOML + env overrides)
  - [x] Implement dynamic config (TOML seed → SQLite authoritative)
  - [x] Implement config event system for hot-reload subscriptions

- [x] Create environment configuration (AC: 4)
  - [x] Create .env.example with all required env vars
  - [x] Document secret management (ANTHROPIC_API_KEY, BRAVE_API_KEY, TELEGRAM_BOT_TOKEN)
  - [x] Implement env variable loading with validation

## Dev Notes

### Critical Architecture Requirements

**Two-Tier Configuration System:**
- **Static Config (Restart Required):** Scope roots, database path, API key env names, log paths
  - Loaded from: `config/default.toml` + environment variables
  - Precedence: code defaults < TOML < env overrides
  - Examples: `scope.allowed_roots`, `database.path`, `logging.file_path`

- **Dynamic Config (Hot Reloadable):** Thresholds, timeouts, retention periods, scheduler settings
  - Seeded from TOML, authoritative in SQLite `config` table
  - Precedence: code defaults < TOML seed < SQLite (authoritative)
  - Examples: `scheduler.tick_seconds`, `files.max_size_mb`, `models.telegram_default`
  - Hot reload via event system (`config_updated` event), subsystems subscribe and apply changes

**Config Registry Pattern:**
```python
# config/registry.py
@dataclass
class ConfigKey:
    tier: Literal["static", "dynamic"]
    value_type: type
    default: Any
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    restart_required: bool = False  # Derived from tier
    validator: Optional[Callable] = None

# Example registrations
REGISTRY = {
    "scope.allowed_roots": ConfigKey(
        tier="static",
        value_type=list,
        default=["~/Projects", "~/Notes"],
        restart_required=True
    ),
    "scheduler.tick_seconds": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=60,
        min_value=10,
        max_value=300,
        restart_required=False
    ),
}
```

**Secrets Management:**
- NEVER store secrets in TOML or SQLite
- Environment variables only: `ANTHROPIC_API_KEY`, `BRAVE_API_KEY`, `TELEGRAM_BOT_TOKEN`
- Config manager references env var NAMES in static config, loads values at runtime
- Secrets NEVER logged (redacted in structlog output)

**Project Structure (7 Subsystems):**
```
sohnbot/
├── src/
│   └── sohnbot/
│       ├── gateway/          # Telegram Gateway (Subsystem 1)
│       ├── runtime/          # Agent Runtime (Subsystem 2)
│       ├── broker/           # Broker Layer (Subsystem 3) ← HEART
│       ├── capabilities/     # Capability Modules (Subsystem 4)
│       │   ├── files/
│       │   ├── git/
│       │   ├── command_profiles/
│       │   ├── search/
│       │   └── scheduler/
│       ├── persistence/      # Persistence Layer (Subsystem 5)
│       ├── supervision/      # Process Supervision (Subsystem 6)
│       └── config/           # Configuration Management (Subsystem 7)
├── tests/
│   ├── unit/
│   └── integration/
├── config/
│   └── default.toml
├── scripts/
├── docs/
├── .env.example
└── pyproject.toml
```

### Technical Requirements

**Python & Dependencies:**
- Python 3.13+ (Story specifies 3.13+, Architecture minimum is 3.10)
- Poetry for dependency management
- Required packages:
  - `claude-agent-sdk` (Agent runtime foundation)
  - `python-telegram-bot` (Telegram Bot API)
  - `aiosqlite` (Async SQLite)
  - `structlog` (Structured logging)
  - `toml` or `tomli` (TOML parsing)
  - `python-dotenv` (Environment variable loading)

**asyncio Architecture:**
- Claude Agent SDK is async-native
- All I/O operations must be async
- Use `asyncio.TaskGroup` for concurrent operations (Python 3.11+)

**Code Organization:**
- **src/ layout** (prevents accidental imports, clean packaging)
- **Subsystem-aligned modules** (maps 1:1 to 7 subsystems)
- **Broker as first-class citizen** (dedicated top-level module)
- All modules initialized with `__init__.py`

### Project Structure Notes

**Alignment with Architecture:**
- ✅ Uses custom architecture-aligned structure (no cookiecutter template)
- ✅ 7 subsystems explicitly organized
- ✅ Broker layer as architectural heart (top-level module)
- ✅ Capability modules separated (not lumped in utils/)
- ✅ src/ layout for clean packaging

**Configuration Files:**
- `config/default.toml` - Seed configuration with both static and dynamic keys
- `config/registry.py` - ConfigKey definitions with tier classification
- `.env.example` - Template for required environment variables

**Directory Creation:**
```bash
mkdir -p src/sohnbot/{gateway,runtime,broker,capabilities/{files,git,command_profiles,search,scheduler},persistence,supervision,config}
mkdir -p tests/{unit,integration,fixtures}
mkdir -p config scripts docs
find src/sohnbot -type d -exec touch {}/__init__.py \;
```

### Testing Requirements

**Testing Framework:**
- pytest (Python standard for async testing)
- Unit tests per subsystem
- Integration tests for config loading and validation

**Test Coverage:**
- Config registry validation (type checking, bounds checking)
- Static config loading (TOML + env precedence)
- Dynamic config seeding to SQLite
- Hot-reload event system
- Secret redaction in logs

### References

**Source Documents:**
- [Architecture: Decision 5 - Configuration & Secrets Management](E:\GIT\SohnBot\_bmad-output\planning-artifacts\architecture.md#Decision-5-Configuration--Secrets-Management)
- [Architecture: Project Structure](E:\GIT\SohnBot\_bmad-output\planning-artifacts\architecture.md#Selected-Starter-Custom-Architecture-Aligned-Structure)
- [Architecture: Implementation Patterns - Configuration Registry](E:\GIT\SohnBot\_bmad-output\planning-artifacts\architecture.md#configuration-registry-pattern)
- [PRD: NFR-022 - Configuration Management](E:\GIT\SohnBot\docs\PRD.md#NFR-022)
- [Epic 1: Story 1.1 Acceptance Criteria](E:\GIT\SohnBot\_bmad-output\planning-artifacts\epics.md#Story-1.1)

### Configuration Target Percentages

**Hot Reload Requirement (NFR-022):**
- Target: 80% of config changes apply without restart
- Architecture achieves ~85% hot-reloadable
- **Hot Reloadable (~85%):** Thresholds, timeouts, retention periods, scheduler settings, logging verbosity, notification settings, model routing
- **Restart Required (~15%):** Scope roots, database path, API keys, logging file path, HTTP server binding

### Implementation Sequence

1. **Initialize Poetry project** with pyproject.toml
2. **Create directory structure** (all 7 subsystems + tests/config/scripts/docs)
3. **Create config registry** (config/registry.py) with ConfigKey class and initial registrations
4. **Create default.toml** with seed values for both static and dynamic config
5. **Create .env.example** with all required secret env vars
6. **Implement config manager** (src/sohnbot/config/manager.py):
   - Static config loader (TOML + env precedence)
   - Dynamic config seeder (TOML → SQLite)
   - Hot-reload event system (asyncio Event, subscriber pattern)
7. **Add __init__.py** to all modules

### Important Notes

**DO NOT create database tables in this story!**
- Database schema is created incrementally across stories
- Story 1.2 creates initial schema (execution_log, config tables)
- Later stories add tables as needed (notifications, scheduler, search_cache)

**No Telegram/Claude SDK integration yet!**
- This story creates the structure only
- Story 1.3 implements Telegram Gateway & Claude Agent SDK Integration
- Story 1.2 implements SQLite Persistence Layer

**Config Table Seeding:**
- Config manager seeds dynamic config to SQLite `config` table
- Requires config table to exist (created in Story 1.2)
- For Story 1.1: Implement seeding logic but document dependency on Story 1.2

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.5

### Debug Log References

N/A - No debug issues encountered

### Completion Notes List

✅ **Project Initialization Complete**
- Created Poetry project with Python 3.13+ configuration
- All dependencies specified in pyproject.toml (claude-agent-sdk, python-telegram-bot, aiosqlite, structlog, python-dotenv)
- Development dependencies configured (pytest, pytest-asyncio, pytest-cov, black, ruff, mypy)
- README.md created with project overview and usage instructions
- .gitignore configured for Python, IDE files, secrets, and runtime data

✅ **Directory Structure Created**
- All 7 subsystems established under src/sohnbot/
- Gateway, Runtime, Broker, Capabilities (with 5 sub-modules), Persistence, Supervision, Config
- Test structure created (unit/, integration/, fixtures/)
- Support directories created (config/, scripts/, docs/, data/)
- All __init__.py files generated for proper Python package structure

✅ **Two-Tier Configuration System Implemented**
- **config/registry.py**: Complete ConfigKey registry with 40+ configuration keys
  - Type validation, bounds checking, custom validators
  - Tier classification (static vs dynamic)
  - Helper functions: get_config_key(), validate_config_value(), get_default_values()
- **config/default.toml**: Seed configuration for all system settings
  - Static config: scope roots, database path, API keys, logging paths
  - Dynamic config: thresholds, timeouts, retention periods, model settings
  - Achieves 85%+ hot-reload target (exceeds NFR-022 requirement of 80%)
- **src/sohnbot/config/manager.py**: Configuration manager with hot-reload support
  - Static config loading from TOML + env overrides
  - Dynamic config seeding (TOML → SQLite when available)
  - Hot-reload event system with subscriber pattern
  - TOML flattening, env variable parsing, validation

✅ **Environment Configuration**
- .env.example created with all required API keys
- Documented secret management: ANTHROPIC_API_KEY, BRAVE_API_KEY, TELEGRAM_BOT_TOKEN
- Environment variable override pattern documented (SOHNBOT_ prefix)

✅ **Comprehensive Test Coverage**
- **tests/unit/test_config_registry.py**: 27 tests covering ConfigKey, registry, validation, security invariants
- **tests/unit/test_config_manager.py**: 27 tests covering static/dynamic config loading, hot-reload, env parsing
- All 54 tests passing (100% pass rate)
- Config manager achieves 89% code coverage

✅ **Acceptance Criteria Validated**
- AC1: Poetry project initialized with Python 3.13+ ✓
- AC2: All directory structure created (7 subsystems) ✓
- AC3: Default configuration loads from config/default.toml ✓
- AC4: Environment variables load from .env ✓
- AC5: Configuration registry validates all keys ✓
- AC6: Hot-reload supported for dynamic config keys ✓

### File List

**Project Configuration:**
- pyproject.toml
- README.md
- .gitignore
- .env.example

**Configuration System:**
- config/registry.py (350 lines - ConfigKey definitions)
- config/default.toml (100 lines - seed configuration)
- src/sohnbot/config/__init__.py
- src/sohnbot/config/manager.py (380 lines - configuration manager)

**Directory Structure:**
- src/sohnbot/__init__.py
- src/sohnbot/gateway/__init__.py
- src/sohnbot/runtime/__init__.py
- src/sohnbot/broker/__init__.py
- src/sohnbot/capabilities/__init__.py
- src/sohnbot/capabilities/files/__init__.py
- src/sohnbot/capabilities/git/__init__.py
- src/sohnbot/capabilities/command_profiles/__init__.py
- src/sohnbot/capabilities/search/__init__.py
- src/sohnbot/capabilities/scheduler/__init__.py
- src/sohnbot/persistence/__init__.py
- src/sohnbot/supervision/__init__.py
- tests/__init__.py
- tests/unit/__init__.py
- tests/integration/__init__.py
- tests/fixtures/__init__.py
- data/.gitkeep

**Tests:**
- tests/unit/test_config_registry.py (450 lines - 27 tests)
- tests/unit/test_config_manager.py (400 lines - 27 tests)

**Total Files Created:** 26 files
**Total Lines of Code:** ~1,680 lines (excluding __init__.py files)
