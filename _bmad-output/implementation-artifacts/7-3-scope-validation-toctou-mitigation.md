# Story 7.3: Scope Validation TOCTOU Mitigation

Status: draft

## Story

As a developer,
I want the scope validator to be resilient against symlink-based TOCTOU attacks,
So that a path cannot pass validation and then be swapped to point outside scope before the file operation executes.

## Acceptance Criteria

**Given** a path that contains symlink components
**When** scope validation runs
**Then** each path component is resolved to detect symlinks pointing outside scope
**And** the final `os.path.realpath()` result is compared against allowed roots
**And** paths with symlinks resolving outside scope are rejected with error code `scope_violation`

**Given** a path that passes initial scope validation
**When** the file operation is about to execute (open/read/write)
**Then** `os.path.realpath()` is called immediately before the I/O call
**And** the real path is re-validated against allowed roots
**And** if the real path is now outside scope, the operation is rejected with a structured error

**Given** a symlink chain where `A -> B -> C` and `C` is outside scope
**When** scope validation is invoked on path `A`
**Then** the full chain is resolved and the final target `C` is validated
**And** the operation is rejected because `C` is outside allowed roots

**Given** a non-existent path within allowed scope
**When** scope validation runs
**Then** the path is accepted (files may not exist yet for write operations)
**And** `strict=False` is used in `Path.resolve()` to handle non-existent segments

## Tasks / Subtasks

- [ ] Task 1: Harden ScopeValidator.validate_path() (AC: 1, 3, 4)
  - [ ] Replace `Path(expanded).resolve(strict=False)` with `os.path.realpath(expanded)` for symlink resolution
  - [ ] Add a separate `_resolve_and_validate(path_str)` method that:
    1. Calls `os.path.realpath(path_str)` to resolve ALL symlinks
    2. Compares the resolved path against `self.allowed_roots`
    3. Returns `(is_valid, resolved_path, error_message)`
  - [ ] Update `validate_path()` to use `_resolve_and_validate()`
  - [ ] Ensure `_normalize_path()` also uses `os.path.realpath()` for root initialization

- [ ] Task 2: Add re-validation at file I/O boundary (AC: 2)
  - [ ] Modify `file_ops.py:read_file()` — call `os.path.realpath(file_path)` immediately before `Path.read_text()` and re-validate via `ScopeValidator.validate_path()`
  - [ ] Modify `file_ops.py:list_files()` — call `os.path.realpath(directory)` immediately before `Path.iterdir()` and re-validate
  - [ ] Modify `patch_editor.py:apply_patch()` — call `os.path.realpath(file_path)` immediately before file write and re-validate
  - [ ] Each re-validation failure raises `FileCapabilityError(code="scope_violation", ...)`
  - [ ] Note: This does NOT eliminate TOCTOU entirely (that requires kernel-level `O_NOFOLLOW`) but reduces the race window to microseconds

- [ ] Task 3: Pass ScopeValidator to FileOps and PatchEditor (AC: 2)
  - [ ] Ensure `FileOps.__init__` and `PatchEditor.__init__` accept a `scope_validator` parameter (verify they already do; if not, add)
  - [ ] Add `self._revalidate_path(path)` convenience method to both classes that calls `self.scope_validator.validate_path(os.path.realpath(path))`
  - [ ] Use `self._revalidate_path()` at the I/O boundary points identified in Task 2

- [ ] Task 4: Testing (AC: all)
  - [ ] Test: symlink inside scope pointing outside scope is rejected
  - [ ] Test: nested symlink chain (A -> B -> C, C outside scope) is rejected
  - [ ] Test: symlink inside scope pointing to another valid location inside scope is accepted
  - [ ] Test: non-existent path inside scope is accepted
  - [ ] Test: re-validation at I/O boundary catches path changes (mock `os.path.realpath` to return different values on 2nd call)
  - [ ] Test: regular paths (no symlinks) continue to work unchanged

## Dev Notes

### Epic 7 Context

**This story:** Fixes F-03 (CRITICAL — TOCTOU race in scope validation).

**Independent of:** All other Story 7.x — can execute in parallel.

### Architecture and Safety Guardrails

1. **TOCTOU Mitigation Strategy:**
   - The fundamental TOCTOU race (check path, then path changes, then open path) cannot be fully eliminated in userspace
   - We mitigate by: (a) resolving symlinks during validation, (b) re-resolving immediately before I/O
   - The race window shrinks from "unbounded" (current) to "microseconds" (after fix)
   - Full elimination would require `O_NOFOLLOW` flags at the `open()` syscall level, which is a Phase 3 consideration

2. **`os.path.realpath()` vs `Path.resolve()`:**
   - `os.path.realpath()` resolves ALL symlinks in the path, including intermediate components
   - `Path.resolve(strict=False)` also resolves symlinks but with different edge case behavior
   - Use `os.path.realpath()` for security-critical resolution because its behavior is more predictable and documented

3. **Non-existent Paths:**
   - Write operations may target files that don't exist yet
   - `os.path.realpath()` resolves what it can and leaves non-existent trailing components as-is
   - This is acceptable — the parent directory is still resolved and validated

### File-Level Guidance

**Primary files to modify:**
- `src/sohnbot/broker/scope_validator.py` — harden `validate_path()`, add `_resolve_and_validate()`
- `src/sohnbot/capabilities/files/file_ops.py` — add re-validation before `read_text()`, `iterdir()`
- `src/sohnbot/capabilities/files/patch_editor.py` — add re-validation before file write

**Files to reference (do not redesign):**
- `src/sohnbot/broker/router.py` — how broker calls `scope_validator.validate_path()` before routing
- `src/sohnbot/capabilities/files/__init__.py` — how FileOps and PatchEditor are constructed

**Files to create for testing:**
- `tests/unit/test_scope_validator_toctou.py` (new — focused symlink tests)

**Files to update for testing:**
- `tests/unit/test_broker.py` — verify broker still calls scope validation correctly

### References

- [Source: _bmad-output/implementation-artifacts/security-audit-findings-v1.md#F-03]
- [Source: docs/PRD.md#DR-002 — Scope Isolation & Path Traversal Prevention]
- [Source: _bmad-output/planning-artifacts/architecture.md — Safety boundary: Scope Validation]
