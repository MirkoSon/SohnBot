"""Unit tests for resilient HTTP observability server restart loop."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.sohnbot.main import _safe_http_server_loop


@pytest.mark.asyncio
async def test_safe_http_server_loop_retries_with_exponential_backoff_and_notifies_after_five():
    attempts = 0

    async def flaky_server(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts <= 5:
            raise RuntimeError(f"boom-{attempts}")
        raise asyncio.CancelledError()

    with (
        patch("src.sohnbot.main.http_server_loop", side_effect=flaky_server),
        patch("src.sohnbot.main.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("src.sohnbot.main.enqueue_notification", new_callable=AsyncMock) as mock_enqueue,
    ):
        with pytest.raises(asyncio.CancelledError):
            await _safe_http_server_loop(host="127.0.0.1", port=8080)

    sleep_delays = [call.args[0] for call in mock_sleep.await_args_list]
    assert sleep_delays[:5] == [2, 4, 8, 16, 32]
    assert mock_enqueue.await_count == 1


@pytest.mark.asyncio
async def test_safe_http_server_loop_propagates_cancelled_error():
    with (
        patch(
            "src.sohnbot.main.http_server_loop",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError(),
        ),
        patch("src.sohnbot.main.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("src.sohnbot.main.enqueue_notification", new_callable=AsyncMock) as mock_enqueue,
    ):
        with pytest.raises(asyncio.CancelledError):
            await _safe_http_server_loop(host="127.0.0.1", port=8080)

    mock_sleep.assert_not_awaited()
    mock_enqueue.assert_not_awaited()
