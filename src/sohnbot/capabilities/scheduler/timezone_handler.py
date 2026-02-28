"""Timezone and DST helpers for scheduler operations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from croniter import croniter

logger = structlog.get_logger(__name__)

_dst_transition_counts: dict[str, int] = {}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _tz_or_utc(timezone_name: str) -> ZoneInfo:
    """Load timezone; fall back to UTC when invalid/unavailable."""
    try:
        return ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001
        logger.warning("invalid_timezone_fallback", timezone=timezone_name, fallback="UTC")
        return ZoneInfo("UTC")


def _increment_dst_counter(dt: datetime) -> None:
    key = dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    _dst_transition_counts[key] = _dst_transition_counts.get(key, 0) + 1


def get_dst_transition_count(day_utc: datetime | None = None) -> int:
    """Return number of handled DST transitions for UTC day."""
    day = (day_utc or _now_utc()).strftime("%Y-%m-%d")
    return int(_dst_transition_counts.get(day, 0))


def format_local_time(utc_timestamp: int, timezone_name: str) -> str:
    """Convert UTC epoch to human-readable local timezone string."""
    tz = _tz_or_utc(timezone_name)
    dt = datetime.fromtimestamp(int(utc_timestamp), tz=timezone.utc).astimezone(tz)
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {tz.key}"


def _roundtrip_matches(local_dt: datetime, tz: ZoneInfo) -> bool:
    as_utc = local_dt.astimezone(timezone.utc)
    back = as_utc.astimezone(tz)
    return (
        back.year == local_dt.year
        and back.month == local_dt.month
        and back.day == local_dt.day
        and back.hour == local_dt.hour
        and back.minute == local_dt.minute
        and back.second == local_dt.second
    )


def handle_dst_transition(job_tz_dt: datetime, timezone_name: str) -> datetime:
    """Adjust local datetime for DST transitions.

    Spring-forward non-existent local times are moved to next valid local time.
    Fall-back ambiguous times resolve to the first occurrence (fold=0).
    """
    tz = _tz_or_utc(timezone_name)
    local = job_tz_dt.astimezone(tz) if job_tz_dt.tzinfo else job_tz_dt.replace(tzinfo=tz)

    candidate_fold0 = local.replace(fold=0)
    candidate_fold1 = local.replace(fold=1)
    match0 = _roundtrip_matches(candidate_fold0, tz)
    match1 = _roundtrip_matches(candidate_fold1, tz)

    if not match0 and not match1:
        # Non-existent local time during spring-forward: move forward to first valid minute.
        probe = local
        for _ in range(180):
            probe = probe + timedelta(minutes=1)
            probe0 = probe.replace(fold=0)
            if _roundtrip_matches(probe0, tz):
                _increment_dst_counter(probe0)
                logger.info(
                    "dst_spring_forward",
                    timezone=tz.key,
                    original=str(local),
                    adjusted=str(probe0),
                )
                return probe0
        logger.warning("dst_spring_forward_unresolved", timezone=tz.key, local=str(local))
        return local

    if match0 and match1:
        # Ambiguous local time during fall-back: use first occurrence.
        chosen = candidate_fold0
        if candidate_fold0.utcoffset() != candidate_fold1.utcoffset():
            _increment_dst_counter(chosen)
            logger.info(
                "dst_fall_back",
                timezone=tz.key,
                local=str(local),
                chosen_fold=0,
                alternative_fold=1,
            )
        return chosen

    # Normal time or a single valid interpretation.
    return candidate_fold0 if match0 else candidate_fold1


def get_next_run_time(
    cron_expr: str,
    timezone_name: str,
    last_completed_slot: int | None = None,
) -> dict[str, Any]:
    """Return next scheduled run time metadata in UTC + local display."""
    tz = _tz_or_utc(timezone_name)
    now_tz = _now_utc().astimezone(tz)

    if last_completed_slot is not None:
        base = datetime.fromtimestamp(int(last_completed_slot), tz=timezone.utc).astimezone(tz)
        if base < now_tz:
            base = now_tz
    else:
        base = now_tz

    next_dt = croniter(cron_expr, base).get_next(datetime)
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=tz)

    adjusted = handle_dst_transition(next_dt, timezone_name=tz.key)
    utc_ts = int(adjusted.astimezone(timezone.utc).timestamp())

    return {
        "utc_timestamp": utc_ts,
        "local_datetime": format_local_time(utc_ts, tz.key),
        "timezone": tz.key,
        "utc": utc_ts,
        "local": format_local_time(utc_ts, tz.key),
    }
