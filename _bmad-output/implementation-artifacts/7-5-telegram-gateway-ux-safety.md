# Story 7.5: Telegram Gateway UX & Safety

Status: draft

## Story

As a user,
I want immediate feedback when I send a message and protection against message floods,
So that I know SohnBot received my request and my Telegram chat doesn't get spammed by a runaway process.

## Acceptance Criteria

**Given** a user sends a message to SohnBot via Telegram
**When** the message passes authentication
**Then** an acknowledgment message ("Processing...") is sent within 2 seconds
**And** the acknowledgment is deleted when the actual response arrives
**And** if processing fails, the acknowledgment is edited to show the error

**Given** SohnBot is sending outbound messages at high volume
**When** the outbound rate exceeds 30 messages per minute
**Then** excess messages are delayed (not dropped)
**And** a structured log warning is emitted at the threshold crossing
**And** the rate limiter uses a sliding-window token bucket

**Given** a scheduled job generates many notifications in rapid succession
**When** the notification worker processes the batch
**Then** messages are sent at no more than 30 per minute
**And** remaining messages stay in the outbox with `pending` status
**And** they are delivered in subsequent poll cycles

## Tasks / Subtasks

- [ ] Task 1: Add immediate acknowledgment to handle_message (AC: 1)
  - [ ] Modify `telegram_client.py:handle_message()` — immediately after auth check, send:
    ```python
    ack_msg = await update.message.reply_text("Processing...")
    ```
  - [ ] Wrap the `route_to_runtime()` call and response sending in try/finally
  - [ ] On success: delete the ack message (`await ack_msg.delete()`), then send actual response
  - [ ] On error: edit the ack message to show error (`await ack_msg.edit_text(...)`)
  - [ ] Handle `telegram.error.BadRequest` if ack message already deleted (race condition)

- [ ] Task 2: Create RateLimiter class (AC: 2)
  - [ ] Create `src/sohnbot/gateway/rate_limiter.py`
  - [ ] Implement `RateLimiter` with sliding-window token bucket:
    ```python
    class RateLimiter:
        def __init__(self, max_per_minute: int = 30):
            self.max_per_minute = max_per_minute
            self._timestamps: deque[float] = deque()

        async def acquire(self) -> None:
            """Wait until a token is available, then consume it."""
            while True:
                now = time.monotonic()
                # Purge timestamps older than 60 seconds
                while self._timestamps and now - self._timestamps[0] > 60:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_per_minute:
                    self._timestamps.append(now)
                    return
                # Wait until the oldest timestamp expires
                wait = 60 - (now - self._timestamps[0]) + 0.1
                await asyncio.sleep(wait)

        def try_acquire(self) -> bool:
            """Non-blocking: return True if token available, False otherwise."""
            ...
    ```
  - [ ] Add structlog warning when queue depth exceeds 80% capacity

- [ ] Task 3: Integrate rate limiter into TelegramClient.send_message (AC: 2, 3)
  - [ ] Add `self._rate_limiter = RateLimiter(max_per_minute=30)` to `TelegramClient.__init__`
  - [ ] Modify `send_message()` — call `await self._rate_limiter.acquire()` before `self.application.bot.send_message()`
  - [ ] The rate limiter applies to ALL outbound messages (direct replies + notification worker)
  - [ ] Make `max_per_minute` configurable via `telegram.max_messages_per_minute` config key

- [ ] Task 4: Add config key for rate limit (AC: 2)
  - [ ] Add to `config/registry.py`:
    ```python
    "telegram.max_messages_per_minute": ConfigKey(
        tier="dynamic",
        value_type=int,
        default=30,
        min_value=5,
        max_value=100,
    ),
    ```

- [ ] Task 5: Testing (AC: all)
  - [ ] Test: handle_message sends ack before route_to_runtime (mock timing)
  - [ ] Test: ack is deleted on successful response
  - [ ] Test: ack is edited to error on failure
  - [ ] Test: RateLimiter allows up to max_per_minute calls without delay
  - [ ] Test: RateLimiter blocks when limit exceeded, unblocks after window slides
  - [ ] Test: send_message calls rate_limiter.acquire before sending
  - [ ] Test: notification_worker respects rate limit via send_message

## Dev Notes

### Epic 7 Context

**This story:** Fixes A-02 (HIGH — no <2s acknowledgment) and A-04 (HIGH — no rate limiting).

**Independent of:** All other Story 7.x — can execute in parallel.

### Architecture and Safety Guardrails

1. **Acknowledgment Pattern:**
   - Send "Processing..." BEFORE any async work
   - Use `reply_text` (not `send_message`) so it appears as a reply to the user's message
   - Delete (not edit) on success to keep chat clean
   - Edit to error message on failure so user sees what went wrong
   - Handle Telegram API errors gracefully (message already deleted, rate limited, etc.)

2. **Rate Limiter Design:**
   - Sliding-window token bucket: simple, accurate, no timer tasks needed
   - `acquire()` is async — blocks the caller until a token is available
   - This naturally backpressures the notification worker without dropping messages
   - Telegram's own rate limit is ~30 msg/s to different chats, ~1 msg/s to same chat
   - Our 30/min limit is much more conservative — prevents spam without hitting Telegram limits

3. **Notification Worker Integration:**
   - The notification worker already calls `self.telegram_client.send_message()`
   - By adding the rate limiter to `send_message()`, the worker automatically respects the limit
   - No changes needed to `notification_worker.py` — it inherits the rate limit via the shared send path

### File-Level Guidance

**Primary files to create:**
- `src/sohnbot/gateway/rate_limiter.py`

**Primary files to modify:**
- `src/sohnbot/gateway/telegram_client.py` — add ack pattern to `handle_message()`, add rate limiter to `__init__` and `send_message()`
- `src/sohnbot/config/registry.py` — add `telegram.max_messages_per_minute` config key

**Files to reference (do not redesign):**
- `src/sohnbot/gateway/notification_worker.py` — verify it uses `self.telegram_client.send_message()` (it does — line ~115)
- `src/sohnbot/gateway/formatters.py` — `format_for_telegram()` for response splitting

**Files to create for testing:**
- `tests/unit/test_rate_limiter.py` (new)

**Files to update for testing:**
- `tests/unit/test_telegram_client.py` — add ack pattern tests

### References

- [Source: _bmad-output/implementation-artifacts/prd-architecture-adherence-audit-v1.md#A-02]
- [Source: _bmad-output/implementation-artifacts/prd-architecture-adherence-audit-v1.md#A-04]
- [Source: docs/PRD.md#DR-006 — Rate Monitoring & Alerts]
- [Source: docs/PRD.md#NFR-019 — <2s response acknowledgment]
