# 🛡️ Project Audit & Polish Plan (SohnBot v1.0)

**Objective**: Conduct a ruthless, adversarial code review of the entire SohnBot codebase using Claude 3 Opus to identify and remediate brittle patterns, concurrency flaws, and technical debt accumulated during rapid development.

---

## 🔍 Audit Focus Areas

The Opus review must specifically interrogate the following architectural pillars:

### 1. Concurrency & State Management
- **Database Locking**: Review `aiosqlite` usage across all modules. Are there race conditions when background schedulers (e.g., `notification_outbox` pollers) overlap with incoming Telegram commands or MCP tool executions?
- **Task Cancellation**: Ensure `asyncio.Task` cleanup is airtight. Are subprocesses (like long-running `git` or `build` profiles) properly terminated if the Telegram user cancels the session or the broker times out?
- **Shared State**: Scrutinize any module-level variables or shared caches (e.g., `ConfigManager` state during hot-reloads) for thread-safety issues.

### 2. Error Handling & Boundaries
- **Swallowed Exceptions**: Search for `except Exception:` blocks. Every catch-all must be justified or replaced with explicitly typed exceptions to prevent state corruption from going unnoticed.
- **Graceful Degradation**: Verify that failures in secondary systems (e.g., `search_volume` tracking or `notification_outbox`) do not crash the primary operational loop (e.g., `brave_search` or command routing).
- **Broker Boundaries**: Ensure the `BrokerRouter` correctly catches, formats, and returns *all* integration failures rather than letting them bubble up to the Telegram client unhandled.

### 3. Security & Validation
- **Path Traversal**: Ruthlessly re-examine the `ScopeValidator`. Can symlinks, absolute path injection, or clever relative pathing bypass the `allowed_roots` jail?
- **Command Injection**: Double-check the `subprocess` arguments in the `profile_executor.py` tools. Are there any vectors where user input (like test patterns or ripgrep queries) could escape the `create_subprocess_exec` boundaries?
- **Metacharacter Filtering**: Validate the regex/validation logic applied to inputs entering the shell environment.

### 4. Type Safety & Domain Modeling
- **Eradicate `Any`**: Identify instances where `dict[str, Any]` is used to pass state between the Broker and MCP tools. Replace with strict `dataclass` or `Pydantic` models where feasible.
- **API Contracts**: Ensure the return types of capabilities (`fs`, `git`, `web`, `session`) strictly match the signatures expected by the Telegram formatting layer and the MCP interface.

### 5. Test Suite Rigor
- **Unhappy Paths**: Are we only testing the "Happy Path"? Challenge Opus to write tests that mock database corruption, network disconnects mid-download, or missing file permissions.
- **Mocking Leaks**: Ensure `patch` and `AsyncMock` usage in integration tests aren't accidentally hiding real-world dependency failures.

---