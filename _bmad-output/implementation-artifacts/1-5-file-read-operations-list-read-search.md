# Story 1.5: File Read Operations (List, Read, Search)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to list, read, and search files within my configured scope,
so that I can query my repositories and notes.

## Acceptance Criteria

**Given** scope validation is enforced  
**When** I request to list files in `~/Projects`  
**Then** all files are returned (excluding `.git`, `.venv`, `node_modules`)  
**And** file paths, sizes, modification times are included  
**And** file read operations complete in <200ms for 1MB files (NFR-001)  
**And** file size limit of 10MB is enforced (FR-008)  
**And** binary files return error: `"Binary files not supported"` (FR-009)  
**And** ripgrep search completes in <5s for 100K file repos (NFR-003)  
**And** regex patterns timeout after 5s (prevents catastrophic backtracking)

## Tasks / Subtasks

- [x] Implement files capability module for Tier-0 read operations (AC: 1, 2, 3, 4, 6, 7, 8)
  - [x] Create `src/sohnbot/capabilities/files/file_ops.py` with `list_files`, `read_file`, `search_files`
  - [x] Exclude traversal directories (`.git`, `.venv`, `node_modules`) from list and search walks
  - [x] Include `path`, `size`, `modified_at` metadata in list response
  - [x] Enforce read size limit (`files.max_size_mb`, default 10MB)
  - [x] Detect binary files and return `"Binary files not supported"`
  - [x] Execute search through `rg` with explicit 5s timeout

- [x] Wire capability through broker/runtime MCP tool path (AC: 1, 8)
  - [x] Add/verify MCP tool registrations:
    - [x] `mcp__sohnbot__files__list`
    - [x] `mcp__sohnbot__files__read`
    - [x] `mcp__sohnbot__files__search`
  - [x] Ensure broker classifies all as Tier 0 (read-only)
  - [x] Ensure scope validation happens before capability execution (rely on Story 1.4 broker path)

- [x] Error handling and response contracts (AC: 5, 6, 8)
  - [x] Return deterministic error for oversize file reads
  - [x] Return deterministic error for binary reads
  - [x] Return deterministic error for search timeout
  - [x] Keep error shape compatible with broker/capability conventions `{code, message, details, retryable}`

- [x] Testing (AC: all)
  - [x] Unit tests for list/read/search happy paths
  - [x] Unit tests for directory exclusions and metadata completeness
  - [x] Unit tests for binary detection and file-size enforcement
  - [x] Unit tests for search timeout and regex behavior guardrails
  - [x] Integration tests through broker route for Tier-0 read-only execution and logging

- [x] Review Follow-ups (AI)
  - [x] [AI-Review][HIGH] Missing Dependency (ripgrep): Added ripgrep to README.md requirements with installation instructions for macOS/Linux/Windows.
  - [x] [AI-Review][MEDIUM] Incomplete Parameter Validation in Broker: Added pattern validation in BrokerRouter.route_operation() for search operations.
  - [x] [AI-Review][LOW] Hardcoded Timeouts in Broker: Added broker.operation_timeout_seconds to config registry; BrokerRouter now consumes timeout from ConfigManager.

## Dev Notes

### Critical Architecture Requirements

- Broker remains the enforcement boundary: scope validation/classification/logging before capability execution.  
  [Source: _bmad-output/planning-artifacts/architecture.md#Core Architectural Requirements]
- Tier model is mandatory: list/read/search are Tier 0 read-only operations.  
  [Source: _bmad-output/planning-artifacts/architecture.md#Core Architectural Requirements]
- Scope and traversal prevention must not be reimplemented in files capability; consume broker guarantees from Story 1.4.
- File read/search constraints are non-negotiable:
  - 10MB read limit
  - search timeout 5s
  - scalability target to 100K files/repo  
  [Source: _bmad-output/planning-artifacts/architecture.md#Technical Constraints & Dependencies]

### Technical Requirements

- Prefer modular file capability layout under `src/sohnbot/capabilities/files/` to match architecture structure (`file_ops.py`), not monolithic `capabilities/files.py`.
- Use `pathlib` for filesystem traversal and metadata extraction.
- For search, use subprocess invocation of `rg` (already an architecture dependency) with:
  - explicit timeout = 5 seconds
  - bounded output handling
  - deterministic parsing to structured matches.
- Binary detection should be deterministic (e.g., null-byte check on sampled bytes) and tested.
- Directory exclusions must apply consistently to both `list_files` and `search_files`.

### Architecture Compliance

- Keep broker responsibilities in broker layer only:
  - scope checks in broker
  - operation classification in broker
  - execution logging lifecycle in broker/audit
- Capability should focus on filesystem and search implementation details.
- Do not bypass broker by exposing direct capability entry points in runtime.

### Library / Framework Requirements

- Python stdlib: `pathlib`, `os`, `stat`, `subprocess` (or `asyncio.create_subprocess_exec` if async path chosen).
- `ripgrep` CLI is required for performant search; fail with actionable error if missing.
- Maintain existing style/tooling constraints from project (`ruff`, `mypy`, `pytest`).

### File Structure Requirements

- Implement under:
  - `src/sohnbot/capabilities/files/file_ops.py`
- Update exports as needed:
  - `src/sohnbot/capabilities/files/__init__.py`
- Runtime/broker tool wiring touchpoints likely include:
  - `src/sohnbot/runtime/mcp_tools.py`
  - broker routing integration points only if currently placeholder-bound

### Testing Requirements

- Unit tests:
  - `tests/unit/test_file_ops.py` (new)
  - cover exclusions, metadata, binary rejection, size rejection, and timeout handling
- Integration tests:
  - `tests/integration/test_file_read_operations.py` (new)
  - verify broker route + Tier-0 behavior + logging side effects
- Include performance-oriented assertions as bounded checks (do not make flaky microbenchmarks mandatory in CI).

### Previous Story Intelligence (From 1.4)

- Story 1.4 required real code fixes during review, not test-only masking.
- Defensive handling of malformed inputs is expected; add explicit path/input validation in files capability boundaries.
- Structured error details and explicit security logging were enforced in 1.4 and should be preserved as pattern.

### Git Intelligence Summary

Recent commits indicate active review-driven hardening in this area:
- `c037c8e` Story 1.4 reviewed and fixed
- `f0ebff3` sprint status updates for story state sync
- `8306a92` prior review fixes addressing multiple findings

Use the same workflow quality bar: implement, test, then code-review before marking done.

### Project Context Reference

No `project-context.md` was discovered in repo at creation time.  
Use architecture + epics as primary context sources for this story.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.5: File Read Operations (List, Read, Search)]
- [Source: _bmad-output/planning-artifacts/architecture.md#Core Architectural Requirements]
- [Source: _bmad-output/planning-artifacts/architecture.md#Technical Constraints & Dependencies]
- [Source: _bmad-output/planning-artifacts/architecture.md#Selected Starter: Custom Architecture-Aligned Structure]
- [Source: _bmad-output/implementation-artifacts/1-4-scope-validation-path-traversal-prevention.md]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- `python -m pytest tests/unit/test_file_ops.py tests/integration/test_file_read_operations.py tests/integration/test_scope_enforcement.py tests/integration/test_broker_integration.py tests/unit/test_broker.py tests/unit/test_mcp_tools.py -v`
- `python -m pytest -v`

### Completion Notes List

- Implemented `FileOps` capability with `list_files`, `read_file`, and `search_files` in `src/sohnbot/capabilities/files/file_ops.py`.
- Added traversal directory exclusions (`.git`, `.venv`, `node_modules`) for list and ripgrep search.
- Enforced read size limits and deterministic binary rejection with `"Binary files not supported"`.
- Added search timeout protection and deterministic capability errors (`search_timeout`, `search_error`, `rg_not_found`).
- Wired broker runtime execution for `fs.read`, `fs.list`, and `fs.search`, returning structured result payloads.
- Added MCP result rendering for file tools and registered `files__read/list/search` aliases.
- Expanded allowed tool list in agent session for `mcp__sohnbot__files__*`.
- Added unit and integration tests for Story 1.5 and updated existing broker/mcp integration tests for concrete capability behavior.
- Full project regression completed successfully: `185 passed, 5 skipped`.

### File List

- `src/sohnbot/capabilities/files/file_ops.py`
- `src/sohnbot/capabilities/files/__init__.py`
- `src/sohnbot/broker/router.py`
- `src/sohnbot/config/registry.py` (added broker.operation_timeout_seconds)
- `config/default.toml` (added [broker] section)
- `README.md` (added ripgrep requirement and installation instructions)
- `src/sohnbot/runtime/mcp_tools.py`
- `src/sohnbot/runtime/agent_session.py`
- `tests/unit/test_file_ops.py`
- `tests/unit/test_pattern_validation.py` (added pattern validation tests)
- `tests/integration/test_file_read_operations.py`
- `tests/integration/test_broker_integration.py`
- `tests/unit/test_broker.py`
- `tests/unit/test_mcp_tools.py`
- `_bmad-output/implementation-artifacts/1-5-file-read-operations-list-read-search.md`

### Change Log

- Implemented Story 1.5 file capability end-to-end with broker wiring, MCP integration, and full regression validation.
- Fixed AI-Review findings (2026-02-26):
  - [HIGH] Added ripgrep to README.md requirements section with installation instructions for all platforms
  - [MEDIUM] Added pattern validation in BrokerRouter for search operations (validates pattern is non-empty string)
  - [LOW] Added broker.operation_timeout_seconds config key; BrokerRouter now consumes timeout from ConfigManager instead of hardcoded 300s
