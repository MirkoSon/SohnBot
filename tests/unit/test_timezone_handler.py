"""Unit tests for scheduler timezone and DST handling."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from src.sohnbot.capabilities.scheduler import timezone_handler
from src.sohnbot.capabilities.scheduler.timezone_handler import (
    format_local_time,
    get_dst_transition_count,
    get_next_run_time,
    handle_dst_transition,
)


@pytest.fixture(autouse=True)
def reset_dst_counter():
    timezone_handler._dst_transition_counts.clear()
    yield
    timezone_handler._dst_transition_counts.clear()


def test_format_local_time_converts_utc_to_local():
    ts = int(datetime(2024, 3, 10, 13, 0, 0, tzinfo=timezone.utc).timestamp())
    value = format_local_time(ts, "America/New_York")
    assert value == "2024-03-10 09:00:00 America/New_York"


def test_get_next_run_time_calculates_next_slot():
    last_completed = int(datetime.now(timezone.utc).timestamp()) - 3600
    result = get_next_run_time("*/5 * * * *", "UTC", last_completed_slot=last_completed)

    assert isinstance(result["utc_timestamp"], int)
    assert result["utc_timestamp"] > last_completed
    assert result["timezone"] == "UTC"
    assert "UTC" in result["local_datetime"]


def test_handle_dst_spring_forward():
    dt = datetime(2024, 3, 10, 2, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    adjusted = handle_dst_transition(dt, "America/New_York")

    assert adjusted.hour == 3
    assert adjusted.minute == 0


def test_handle_dst_fall_back():
    dt = datetime(2024, 11, 3, 1, 30, 0, fold=1, tzinfo=ZoneInfo("America/New_York"))
    adjusted = handle_dst_transition(dt, "America/New_York")

    assert adjusted.fold == 0


def test_dst_transition_logging():
    dt = datetime(2024, 3, 10, 2, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    handle_dst_transition(dt, "America/New_York")

    assert get_dst_transition_count(datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)) == 1


def test_invalid_timezone_fallback():
    ts = int(datetime(2024, 3, 10, 13, 0, 0, tzinfo=timezone.utc).timestamp())
    value = format_local_time(ts, "Invalid/Timezone")
    assert value.endswith("UTC")
