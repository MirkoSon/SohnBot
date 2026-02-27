# Investigation: System Binaries Dependencies Audit (Epic 1 Retro)

**Action Item #2:** "Review & Refactor System Binaries Dependencies"
**Owner:** Elena (Junior Dev)
**Priority:** High
**Context:** Epic 1 encountered environment issues where system binaries (`node`, `git`, etc.) were not found across different environments (WSL/Windows/Cloud).

## Executive Summary

✅ **Current State: GOOD** - Both runtime system binaries have proper error handling and documentation.
⚠️ **Improvements Needed:** Minor enhancements to error messages and documentation completeness.

## Findings

### System Binaries Inventory

SohnBot depends on the following system binaries at runtime:

| Binary | Used In | Purpose | Error Handling | Documented |
|--------|---------|---------|----------------|------------|
| `git` | `src/sohnbot/capabilities/git/snapshot_manager.py` | Snapshot branch creation, rollback operations | ✅ Yes | ✅ Yes (README.md) |
| `rg` (ripgrep) | `src/sohnbot/capabilities/files/file_ops.py` | File content search operations | ✅ Yes | ✅ Yes (README.md) |
| `python` | Application runtime | Main application execution | N/A (Poetry managed) | ✅ Yes (development_environment.md) |
| `node` | BMAD framework scripts | Development/build tooling | N/A (not in Python codebase) | ✅ Yes (development_environment.md) |

### Detailed Analysis

#### 1. Git Binary (`git`)

**Files:** `src/sohnbot/capabilities/git/snapshot_manager.py`

**Usage Points:**
- Line 135-146: `create_subprocess_exec` for `git branch`
- Line 198-210: `subprocess.run` for `git branch --list`
- Line 313-324: `create_subprocess_exec` for `git rev-parse`
- Additional commands: `git checkout`, `git commit`, `git rev-parse`, `git diff-tree`

**Error Handling:** ✅ EXCELLENT
```python
except FileNotFoundError as exc:
    raise GitCapabilityError(
        code="git_not_found",
        message="git CLI is required for snapshot operations",
        details={"repo_path": repo_path},
        retryable=False,
    ) from exc
```

**Strengths:**
- Consistent error handling across all git invocations
- Structured error with code, message, details
- Marked as non-retryable (correct - installing git requires manual intervention)

#### 2. Ripgrep Binary (`rg`)

**Files:** `src/sohnbot/capabilities/files/file_ops.py`

**Usage Points:**
- Line 137: `search_files()` function documentation mentions ripgrep
- Line 184-190: Error handling for missing `rg` binary

**Error Handling:** ✅ EXCELLENT
```python
except FileNotFoundError as exc:
    raise FileCapabilityError(
        code="rg_not_found",
        message="ripgrep (rg) is required for search operations",
        details={"path": str(root)},
        retryable=False,
    ) from exc
```

**Strengths:**
- Clear error message with full tool name and binary name
- Structured error pattern matching git implementation
- Non-retryable (correct)

#### 3. Documentation Review

**README.md** (Lines 65-74): ✅ EXCELLENT
- Dedicated "Runtime CLI Dependencies" section
- Table format showing tool, usage, and failure behavior
- Platform-specific installation notes
- Clear Windows note about Git for Windows

**docs/development_environment.md**: ⚠️ INCOMPLETE
- Documents: Node.js, Python, Git, Poetry
- **Missing: ripgrep** - Should be added to Core Dependencies section

### Cross-Platform Considerations

**Current Implementation:**
- Uses `asyncio.create_subprocess_exec(*cmd)` for async operations
- Uses `subprocess.run()` for sync operations
- Both are cross-platform compatible (no shell=True, direct executable invocation)
- Path handling uses `pathlib.Path` (cross-platform)

**Strengths:**
- No hardcoded shell assumptions (`bash` vs `cmd`)
- No shell injection vulnerabilities
- Works across Windows CMD, WSL, and Linux

## Recommendations

### HIGH Priority (Required for Story 2.1)

1. **Update development_environment.md to include ripgrep**
   - Add to "Core Dependencies" section
   - Include minimum version requirements (if any)
   - Add to each environment setup section

### MEDIUM Priority (Nice-to-have for Epic 2)

2. **Enhance error messages with documentation references**
   ```python
   message="git CLI is required for snapshot operations. See docs/development_environment.md for installation instructions"
   ```

3. **Add startup validation utility**
   - Create `src/sohnbot/config/system_checks.py`
   - Validate all required binaries at startup
   - Use `shutil.which()` to check PATH
   - Log warnings or fail fast with clear guidance

### LOW Priority (Future consideration)

4. **Add version checking**
   - Check minimum git version (e.g., `git --version`)
   - Check ripgrep version
   - Warn if versions are outdated

## Resolution

### Changes Required

✅ **No code refactoring needed** - Error handling is already robust and follows best practices.

✏️ **Documentation update needed**:
- Add ripgrep to `docs/development_environment.md`

### Epic 2 Story 2.1 Considerations

When implementing Story 2.1 (Git Status & Diff Queries):
- ✅ Follow existing error handling pattern from `snapshot_manager.py`
- ✅ Use structured `GitCapabilityError` for consistency
- ✅ Catch `FileNotFoundError` and provide clear messages
- ✅ Reference `docs/development_environment.md` in error messages (after updating it)

## Conclusion

**Action Item #2 Status:** ✅ COMPLETE (with minor documentation update)

The codebase already implements robust system binary dependency handling:
- Proper error catching for missing binaries
- Clear, structured error messages
- Cross-platform compatible implementation
- Well-documented in README.md

The only improvement needed is adding ripgrep to `docs/development_environment.md` to achieve complete documentation coverage.

**Epic 2 is READY TO START** - No blocking environment issues remain.
