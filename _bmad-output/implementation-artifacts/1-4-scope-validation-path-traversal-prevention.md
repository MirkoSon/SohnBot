# Story 1.4: Scope Validation & Path Traversal Prevention

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want all file operations restricted to configured scope roots,
So that SohnBot cannot access files outside ~/Projects or ~/Notes.

## Acceptance Criteria

**Given** scope roots are configured (~/Projects, ~/Notes)
**When** any file operation is requested with a path
**Then** path is normalized to absolute path (resolve symlinks, relative paths)
**And** path traversal attempts (../, ~, symlinks outside scope) are rejected
**And** rejection returns error: "Path outside allowed scope"
**And** broker validates scope before executing any file capability
**And** 100% of path traversal attempts are blocked (NFR-010)

## Tasks / Subtasks

- [x] Create Scope Validator Module (AC: 1, 2, 3, 4)
  - [x] Create src/sohnbot/broker/scope_validator.py
  - [x] Implement path normalization (resolve symlinks, expand ~, make absolute)
  - [x] Implement traversal prevention (check normalized path starts with allowed root)
  - [x] Return structured error for violations: {"code": "scope_violation", "message": "...", "details": {...}, "retryable": False}

- [x] Configuration Integration (AC: 1)
  - [x] Add scope.allowed_roots to config/default.toml with default: ["~/Projects", "~/Notes"]
  - [x] Add scope.allowed_roots to config registry (static tier, restart required)
  - [x] Document scope roots in .env.example

- [x] Broker Integration (AC: 5)
  - [x] Import scope_validator in broker/router.py
  - [x] Call validate_path() before routing file operations
  - [x] Return BrokerResult(allowed=False) for scope violations
  - [x] Log scope violations with chat_id and attempted path

- [x] Comprehensive Testing (AC: all, NFR-010)
  - [x] Unit tests: test_scope_validator.py (path normalization, traversal detection)
  - [x] Integration tests: test_scope_enforcement.py (broker blocks violations)
  - [x] Security tests: Verify 100% blocking of traversal techniques (../, symlinks, ~, absolute paths)

## Dev Notes

### Critical Architecture Requirements

**Security Boundary (NON-NEGOTIABLE):**
- Scope validation is a **security boundary** - 100% blocking requirement (NFR-010)
- Path traversal prevention MUST be architectural, not prompt-based
- All file operations MUST pass through scope validation before execution
- No model (Haiku, Sonnet, Opus) can bypass scope restrictions
- Validation occurs in broker layer BEFORE routing to capabilities

**Validation Order (Governed-Operator Spine):**
```
1. PreToolUse Hook → Block non-mcp__sohnbot__* tools
2. Broker Validation:
   ├─ Generate operation_id
   ├─ Classify tier (0/1/2/3)
   ├─ **Validate scope** ← THIS STORY
   ├─ Check limits
   └─ Log operation start
3. Capability Execution
4. Log operation end
```

**Scope Validation Must Occur:**
- **BEFORE** capability routing (broker layer)
- **AFTER** tier classification
- **BEFORE** operation logging
- For **ALL** file operations (Tier 0, 1, 2)

### Technical Implementation Requirements

**Module: src/sohnbot/broker/scope_validator.py**

**Purpose:** Path normalization and traversal prevention for all file operations.

**Required Functions:**

```python
class ScopeValidator:
    """Validates file paths against configured scope roots."""

    def __init__(self, allowed_roots: list[str]):
        """
        Initialize validator with allowed scope roots.

        Args:
            allowed_roots: List of allowed directory paths (can contain ~ and relative paths)
        """
        # Normalize and expand all roots to absolute paths
        # Store normalized roots for comparison

    def validate_path(self, path: str) -> tuple[bool, str]:
        """
        Validate path against allowed scope roots.

        Args:
            path: File or directory path to validate (any format: relative, ~, symlink)

        Returns:
            Tuple of (is_valid: bool, error_message: str or "")

        Logic:
            1. Normalize path to absolute:
               - os.path.expanduser() for ~ expansion
               - Path.resolve(strict=False) for symlinks + relative paths
               - Handle Windows vs Unix path differences
            2. Check if normalized path starts with ANY allowed root
            3. Return (True, "") if valid
            4. Return (False, "Path outside allowed scope: {path}") if invalid

        Edge Cases:
            - Symlinks pointing outside scope → REJECT
            - ../ traversal attempts → REJECT (resolved to absolute)
            - Absolute paths outside scope → REJECT
            - ~ expansion to user home outside scope → REJECT
            - Paths that don't exist yet → ALLOW (for file creation)
        """
```

**Error Structure (MUST MATCH ARCHITECTURE):**

```python
{
    "code": "scope_violation",           # snake_case
    "message": "Path outside allowed scope",
    "details": {"path": normalized_path, "allowed_roots": allowed_roots},
    "retryable": False                   # User cannot retry with same path
}
```

**Configuration Integration:**

File: `config/default.toml`
```toml
[scope]
allowed_roots = ["~/Projects", "~/Notes"]
```

Registry entry in `src/sohnbot/config/registry.py`:
```python
ConfigKey(
    key="scope.allowed_roots",
    tier="static",  # Restart required (security boundary)
    value_type=list[str],
    default=["~/Projects", "~/Notes"],
    description="Allowed directory roots for file operations",
    restart_required=True
)
```

**Broker Integration:**

File: `src/sohnbot/broker/router.py`

Location: In `route_operation()` method, AFTER tier classification, BEFORE limit checking:

```python
# 3. Validate scope (if file operation)
if capability == "fs":
    # Check both singular 'path' and plural 'paths'
    paths_to_validate = []
    if "path" in params:
        paths_to_validate.append(params["path"])
    if "paths" in params and isinstance(params["paths"], list):
        paths_to_validate.extend(params["paths"])

    for path in paths_to_validate:
        is_valid, error_msg = self.scope_validator.validate_path(path)
        if not is_valid:
            # Clean up operation start time to prevent memory leak
            del self._operation_start_times[operation_id]
            return BrokerResult(
                allowed=False,
                operation_id=operation_id,
                tier=tier,
                error={
                    "code": "scope_violation",
                    "message": error_msg,
                    "details": {"path": path},
                    "retryable": False,
                },
            )
```

**Important Note:** This code ALREADY EXISTS in broker/router.py (lines 77-101)!
- The broker is already calling `self.scope_validator.validate_path(path)`
- **Your job:** Implement the ScopeValidator class that broker is already using
- Check broker/__init__.py to see how ScopeValidator is instantiated

### Path Normalization Techniques (Security Critical)

**Must Handle ALL These Cases:**

1. **Relative paths:** `../../etc/passwd` → Resolve to absolute, check against roots
2. **Tilde expansion:** `~/../../etc/passwd` → Expand ~, then resolve
3. **Symlinks:** `link_to_root/../../etc/passwd` → Follow symlink, then resolve
4. **Absolute paths:** `/etc/passwd` → Directly check against roots
5. **Windows paths:** `C:\Windows\System32` → Handle drive letters
6. **Mixed separators:** `C:\Projects/subfolder\..\..` → Normalize separators
7. **Nonexistent paths:** `~/Projects/new_file.txt` → Allow (for creation)
8. **Current directory:** `./file.txt` → Resolve relative to cwd

**Python Standard Library Functions:**

```python
from pathlib import Path
import os

# Expand ~ to user home directory
expanded = os.path.expanduser(path)

# Resolve symlinks and relative paths (strict=False allows nonexistent)
resolved = Path(expanded).resolve(strict=False)

# Check if path starts with allowed root
is_valid = str(resolved).startswith(str(allowed_root))
```

**Security Considerations:**

- Use `Path.resolve(strict=False)` to allow file creation
- Compare absolute paths, not strings (avoid bypass via `/./` or `/a/../`)
- On Windows, compare case-insensitively (C: == c:)
- Log ALL violations with chat_id for security auditing

### Testing Requirements

**Unit Tests: tests/unit/test_scope_validator.py**

Must test 100% of traversal techniques:

```python
class TestScopeValidator:
    """Test path normalization and traversal prevention."""

    @pytest.fixture
    def validator(self):
        return ScopeValidator(allowed_roots=["~/Projects", "~/Notes"])

    # Path Normalization Tests
    def test_relative_path_normalized(self, validator):
        """Relative paths resolved to absolute."""
        # Test ../../../etc/passwd → rejected

    def test_tilde_expansion(self, validator):
        """~ expands to user home."""
        # Test ~/Projects/file.txt → allowed
        # Test ~/../../etc/passwd → rejected

    def test_symlink_resolution(self, validator):
        """Symlinks resolved before validation."""
        # Create symlink pointing outside scope
        # Verify rejection after resolution

    def test_nonexistent_path_allowed(self, validator):
        """Paths that don't exist yet are allowed."""
        # Test ~/Projects/new_file.txt → allowed

    # Traversal Prevention Tests
    def test_parent_directory_traversal_blocked(self, validator):
        """../ traversal attempts rejected."""

    def test_absolute_path_outside_scope_blocked(self, validator):
        """/etc/passwd rejected."""

    def test_symlink_to_outside_scope_blocked(self, validator):
        """Symlinks pointing outside scope rejected."""

    # Valid Path Tests
    def test_allowed_root_path_valid(self, validator):
        """Paths within allowed roots pass."""

    def test_subdirectory_in_allowed_root_valid(self, validator):
        """Subdirectories within scope pass."""
```

**Integration Tests: tests/integration/test_scope_enforcement.py**

Test broker-level enforcement:

```python
class TestBrokerScopeEnforcement:
    """Test broker rejects scope violations."""

    @pytest.mark.asyncio
    async def test_broker_blocks_traversal_attempt(self):
        """Broker returns allowed=False for ../../../etc/passwd."""

    @pytest.mark.asyncio
    async def test_broker_allows_valid_path(self):
        """Broker returns allowed=True for ~/Projects/file.txt."""

    @pytest.mark.asyncio
    async def test_broker_logs_scope_violation(self):
        """Scope violations logged to audit trail."""
```

**Security Test Coverage (NFR-010 Validation):**

Create comprehensive security test suite:

```python
@pytest.mark.parametrize("malicious_path", [
    "../../etc/passwd",
    "../../../root/.ssh/id_rsa",
    "~/../../etc/shadow",
    "/etc/passwd",
    "C:\\Windows\\System32\\config\\SAM",
    "link_to_root/../../etc/passwd",
    "~/../../../etc/hosts",
])
async def test_100_percent_traversal_blocking(malicious_path):
    """Verify ALL path traversal techniques blocked."""
    result = await broker.route_operation(
        capability="fs",
        action="read",
        params={"path": malicious_path},
        chat_id="test"
    )
    assert result.allowed == False
    assert result.error["code"] == "scope_violation"
```

### Project Structure Alignment

**Files to Create:**
- `src/sohnbot/broker/scope_validator.py` (new, ~80 lines)

**Files to Modify:**
- `src/sohnbot/broker/router.py` (import ScopeValidator, instantiate in __init__)
- `src/sohnbot/broker/__init__.py` (export ScopeValidator)
- `src/sohnbot/config/registry.py` (add scope.allowed_roots config key)
- `config/default.toml` (add [scope] section with allowed_roots)

**Files Already Expecting This:**
- `src/sohnbot/broker/router.py:87` - Already calls `self.scope_validator.validate_path(path)`!
- Broker is currently failing because ScopeValidator doesn't exist yet

**Test Files to Create:**
- `tests/unit/test_scope_validator.py` (~150 lines, 12+ test cases)
- `tests/integration/test_scope_enforcement.py` (~80 lines, 5+ test cases)

### Patterns from Previous Stories

**From Story 1.2 (Broker Foundation):**
- Broker router pattern already established
- Operation classification (Tier 0/1/2/3) working
- BrokerResult dataclass pattern
- Structured error handling: {code, message, details, retryable}

**From Story 1.3 (Gateway/Runtime):**
- structlog for all logging
- Async/await patterns throughout
- Comprehensive test coverage (unit + integration)
- Error handling with try/except/finally
- snake_case naming convention
- Type hints for all function signatures

**Code Review Process:**
- Implementation → Code Review (Opus) → Fixes → Status Update
- Expect 10-15 findings per story
- Common issues: Missing error handling, incomplete tests, dead code
- Fix all findings before marking story done

### References

**Architecture:**
- [Source: \_bmad-output/planning-artifacts/architecture.md#Decision 2: Broker-Centric Policy Enforcement]
  - Validation order (Hook → Broker → Capability → Execute → Log)
  - Scope validation in broker layer
  - Error structure specification

- [Source: \_bmad-output/planning-artifacts/architecture.md#Security Boundaries]
  - NFR-010: Path Traversal Prevention (100% blocked)
  - NFR-012: Scope Violation Prevention (100% rejected)
  - Architectural enforcement, not prompt-based

- [Source: \_bmad-output/planning-artifacts/architecture.md#Code Patterns]
  - snake_case for functions (validate_scope, normalize_path)
  - Error structure: {code, message, details, retryable}
  - Async patterns with proper error handling

**Epic Specification:**
- [Source: \_bmad-output/planning-artifacts/epics.md#Story 1.4]
  - User story and acceptance criteria
  - Implementation notes
  - FR-020 (Scope Validation), FR-021 (Configured Scope Roots)

**Previous Implementation:**
- [Source: src/sohnbot/broker/router.py:77-101]
  - Scope validation call already implemented
  - Expects self.scope_validator.validate_path(path)
  - Returns BrokerResult with error on violation

**Configuration System:**
- [Source: src/sohnbot/config/registry.py]
  - ConfigKey pattern for registry
  - Static tier for security boundaries (restart_required=True)

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- `.venv/bin/python -m pytest tests/unit/test_scope_validator.py tests/integration/test_scope_enforcement.py -v`
- `.venv/bin/python -m pytest tests/integration -v`

### Completion Notes List

- Implemented `ScopeValidator` path normalization using `expanduser` + `Path.resolve(strict=False)` and safe mixed-separator handling.
- Added robust path type handling to prevent broker crashes on malformed `path` payloads.
- Updated broker scope violation responses to include structured details: attempted path, normalized path, and allowed roots.
- Added explicit scope violation warning logs with `chat_id`, attempted path, normalized path, and allowed roots.
- Added integration coverage for malformed path types and concrete scope-violation log assertions.
- Verified scope unit+integration suite passes and full integration suite remains green.

### File List

- `src/sohnbot/broker/scope_validator.py`
- `src/sohnbot/broker/router.py`
- `tests/unit/test_scope_validator.py`
- `tests/integration/test_scope_enforcement.py`
- `config/default.toml`
- `src/sohnbot/config/registry.py`
- `.env.example`
