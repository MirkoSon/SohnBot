# Story 7.6: Configuration System Completion

Status: draft

## Story

As a user,
I want to view and modify SohnBot's configuration via Telegram commands,
So that I can tune thresholds, timeouts, and settings without editing files or restarting the process.

## Acceptance Criteria

**Given** the user sends `/config show` via Telegram
**When** the command is processed
**Then** all config keys are displayed grouped by tier (static/dynamic)
**And** dynamic keys show their current value and default value
**And** static keys are marked as "requires restart to change"
**And** the response is formatted for Telegram readability (truncated if >4096 chars)

**Given** the user sends `/config set thresholds.search_volume_daily=200`
**When** the command is processed
**Then** the key is validated against the config registry (type, bounds, tier)
**And** if the key is dynamic, the value is updated in-memory AND persisted to the `config` table
**And** the user receives confirmation: "Updated thresholds.search_volume_daily = 200"
**And** if the key is static, the user receives: "Key [key] is static — update config/default.toml and restart"
**And** if validation fails, the user receives the specific error (type mismatch, out of bounds, unknown key)

**Given** the user sends `/config reset thresholds.search_volume_daily`
**When** the command is processed
**Then** the key is reset to its default value (from registry)
**And** the persisted value is removed from the `config` table
**And** the user receives confirmation with the restored default value

**Given** the user sends `/config` with no subcommand or an invalid subcommand
**When** the command is processed
**Then** a usage help message is returned: "Usage: /config show | set <key>=<value> | reset <key>"

## Tasks / Subtasks

- [ ] Task 1: Create handle_config_command in commands.py (AC: 1, 2, 3, 4)
  - [ ] Add `async def handle_config_command(chat_id: str, command_text: str) -> str:` to `gateway/commands.py`
  - [ ] Parse subcommand: `show`, `set`, `reset`
  - [ ] For `show`:
    1. Get ConfigManager instance
    2. Iterate registry keys, group by tier
    3. Format as monospace text: `key = value (default: X) [dynamic]` or `key = value [static, restart required]`
    4. Truncate to 4000 chars if needed (Telegram 4096 limit minus formatting overhead)
  - [ ] For `set`:
    1. Parse `key=value` from args (split on first `=`)
    2. Coerce value to expected type from registry (int, float, str, bool)
    3. Call `config_manager.update_dynamic_config(key, value)`
    4. Return success message or error message
  - [ ] For `reset`:
    1. Parse key from args
    2. Call `config_manager.reset_dynamic_config(key)`
    3. Return confirmation with restored default

- [ ] Task 2: Register /config command handler in TelegramClient (AC: all)
  - [ ] Add `CommandHandler("config", self.cmd_config)` in `telegram_client.py:start()`
  - [ ] Add `cmd_config` method following the same pattern as `cmd_status`, `cmd_health`, etc.:
    ```python
    async def cmd_config(self, update: Update, context):
        if not update.message or not update.effective_chat:
            return
        chat_id = update.effective_chat.id
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning("unauthorized_config_command", chat_id=chat_id)
            return
        response = await handle_config_command(str(chat_id), update.message.text or "")
        await update.message.reply_text(response)
    ```
  - [ ] Add `handle_config_command` to the imports from `.commands`

- [ ] Task 3: Add ConfigManager.reset_dynamic_config() (AC: 3)
  - [ ] Add method to `config/manager.py`:
    ```python
    async def reset_dynamic_config(self, key: str) -> Any:
        config_key_def = get_config_key(key)
        if config_key_def.tier != "dynamic":
            raise KeyError(f"Cannot reset static config key '{key}'")
        default = config_key_def.default
        self.dynamic_config[key] = default
        # Delete from DB (persistence from Story 7.1)
        await self._delete_persisted_config(key)
        await self._notify_subscribers(key, default)
        return default
    ```
  - [ ] Add `_delete_persisted_config(key)` — DELETE FROM config WHERE key = ?

- [ ] Task 4: Add type coercion helper for config set (AC: 2)
  - [ ] Create `_coerce_config_value(key: str, raw_value: str) -> Any` in `commands.py` or `manager.py`
  - [ ] Look up expected type from registry: `get_config_key(key).value_type`
  - [ ] Convert: `"true"/"false"` → bool, numeric strings → int/float, else str
  - [ ] Raise `ValueError` with clear message on type mismatch

- [ ] Task 5: Testing (AC: all)
  - [ ] Test: `/config show` returns grouped output with all keys
  - [ ] Test: `/config set scheduler.tick_seconds=120` updates dynamic config and returns success
  - [ ] Test: `/config set` with static key returns "restart required" message
  - [ ] Test: `/config set` with invalid key returns error
  - [ ] Test: `/config set` with out-of-bounds value returns validation error
  - [ ] Test: `/config reset scheduler.tick_seconds` restores default and returns confirmation
  - [ ] Test: `/config` with no args returns usage
  - [ ] Test: unauthorized chat_id is rejected

## Dev Notes

### Epic 7 Context

**This story:** Fixes A-03 (HIGH — `/config` commands not implemented). Depends on Story 7.1 for DB persistence backend.

**Dependency:** Story 7.1 must complete first — it implements `_persist_to_database()` and `load_dynamic_config_from_db()`.

### Architecture and Safety Guardrails

1. **Config Command Security:**
   - Only authorized Telegram chat IDs can use `/config` (same auth as all other commands)
   - Static config keys cannot be modified at runtime — explicit error message returned
   - All value changes go through registry validation (type, bounds, validator functions)
   - Changes are logged via structlog (already done in `update_dynamic_config()`)

2. **Response Formatting:**
   - Telegram messages have a 4096-character limit
   - For `/config show`, group by tier and truncate if needed
   - Use monospace formatting (backticks) for key-value pairs
   - Consider splitting into multiple messages if config grows large

3. **Type Coercion:**
   - Config values arrive as strings from Telegram
   - Registry defines expected types: `int`, `float`, `str`, `bool`
   - Boolean: accept `true/false`, `yes/no`, `1/0` (case-insensitive)
   - Numeric: use `int()` or `float()` with clear error on failure

### File-Level Guidance

**Primary files to modify:**
- `src/sohnbot/gateway/commands.py` — add `handle_config_command()`
- `src/sohnbot/gateway/telegram_client.py` — register `/config` handler, add `cmd_config()`
- `src/sohnbot/config/manager.py` — add `reset_dynamic_config()`, `_delete_persisted_config()`

**Files to reference (do not redesign):**
- `src/sohnbot/gateway/commands.py:263-438` — `/schedule` command pattern (complex subcommands)
- `src/sohnbot/config/registry.py` — `get_config_key()`, `CONFIG_REGISTRY`, `ConfigKey` dataclass
- `src/sohnbot/config/manager.py:237-275` — `update_dynamic_config()` existing implementation

**Files to create for testing:**
- `tests/unit/test_config_command.py` (new)

**Files to update for testing:**
- `tests/unit/test_telegram_client.py` — add `/config` handler registration test

### References

- [Source: _bmad-output/implementation-artifacts/prd-architecture-adherence-audit-v1.md#A-03]
- [Source: _bmad-output/planning-artifacts/architecture.md — Architecture Decision 5: Two-Tier Configuration]
- [Source: docs/PRD.md#FR-021 — Configured Scope Roots]
