"""Unit tests for Telegram gateway rate limiter."""

import asyncio

import pytest

from src.sohnbot.gateway.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_allows_up_to_limit_without_sleep(monkeypatch):
    limiter = RateLimiter(max_per_minute=3)

    now = {"value": 1000.0}
    monkeypatch.setattr("src.sohnbot.gateway.rate_limiter.time.monotonic", lambda: now["value"])

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        now["value"] += delay

    monkeypatch.setattr("src.sohnbot.gateway.rate_limiter.asyncio.sleep", fake_sleep)

    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()

    assert sleep_calls == []


@pytest.mark.asyncio
async def test_rate_limiter_blocks_when_limit_exceeded_then_unblocks(monkeypatch):
    limiter = RateLimiter(max_per_minute=1)

    now = {"value": 1000.0}
    monkeypatch.setattr("src.sohnbot.gateway.rate_limiter.time.monotonic", lambda: now["value"])

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        now["value"] += delay

    monkeypatch.setattr("src.sohnbot.gateway.rate_limiter.asyncio.sleep", fake_sleep)

    await limiter.acquire()  # consume first slot
    await limiter.acquire()  # must wait until window slides

    assert len(sleep_calls) == 1
    assert sleep_calls[0] >= 60.0


@pytest.mark.asyncio
async def test_try_acquire_non_blocking(monkeypatch):
    limiter = RateLimiter(max_per_minute=1)
    now = {"value": 1000.0}
    monkeypatch.setattr("src.sohnbot.gateway.rate_limiter.time.monotonic", lambda: now["value"])

    assert await limiter.try_acquire() is True
    assert await limiter.try_acquire() is False
