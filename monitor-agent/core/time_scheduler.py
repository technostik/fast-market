from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import Rule

_INTERVAL_PATTERN = re.compile(r"^(\d+)([smhd])$")


def parse_interval(interval_str: str) -> timedelta:
    """Parse interval string (e.g., '1h', '30m', '1d', '30s') to timedelta."""
    match = _INTERVAL_PATTERN.match(interval_str)
    if not match:
        raise ValueError(
            f"Invalid interval format: '{interval_str}'. Expected format: "
            "'<number><unit>' where unit is s (seconds), m (minutes), h (hours), d (days)"
        )

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "s":
        return timedelta(seconds=value)
    elif unit == "m":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)

    raise ValueError(f"Unknown interval unit: {unit}")


def parse_cron(cron_expr: str) -> dict[str, int | str]:
    """Parse cron expression string to dict."""
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(
            f"Invalid cron expression: '{cron_expr}'. Expected 5 fields: "
            "minute hour day month weekday"
        )

    try:
        from croniter import croniter

        croniter(cron_expr)
    except Exception as e:
        raise ValueError(f"Invalid cron expression: '{cron_expr}'. {e}")

    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def parse_schedule(schedule_dict: dict | None) -> str | None:
    """Parse schedule dict to human-readable string."""
    if schedule_dict is None:
        return None

    if "cron" in schedule_dict:
        return f"cron: {schedule_dict['cron']}"
    elif "interval" in schedule_dict:
        return f"interval: {schedule_dict['interval']}"

    return None


def should_run_rule(rule: Rule, current_time: datetime | None = None) -> bool:
    """Check if rule should run based on its schedule.

    Args:
        rule: The rule to check
        current_time: Current time (defaults to now in UTC)

    Returns:
        True if rule should run, False otherwise
    """
    if rule.schedule is None:
        return True

    if current_time is None:
        current_time = datetime.now(timezone.utc)

    tz = timezone.utc
    if rule.timezone and rule.timezone != "UTC":
        try:
            import pytz

            tz = pytz.timezone(rule.timezone)
        except Exception:
            tz = timezone.utc

    local_time = current_time.astimezone(tz)

    if "cron" in rule.schedule:
        cron_expr = rule.schedule["cron"]
        return _should_run_cron(cron_expr, local_time, rule.last_triggered_at, tz)

    elif "interval" in rule.schedule:
        interval_str = rule.schedule["interval"]
        return _should_run_interval(interval_str, rule.last_triggered_at, current_time)

    return True


def _should_run_cron(
    cron_expr: str,
    current_time: datetime,
    last_triggered: datetime | None,
    tz: timezone,
) -> bool:
    """Check if cron expression matches current time and hasn't triggered yet."""
    try:
        from croniter import croniter

        cron = croniter(cron_expr, current_time)
        cron.get_next(datetime)

        if last_triggered is None:
            return True

        last_triggered_local = last_triggered.astimezone(tz)
        cron = croniter(cron_expr, current_time)
        prev_run = cron.get_prev(datetime)

        if prev_run > last_triggered_local:
            return True

        return False
    except Exception:
        return True


def _should_run_interval(
    interval_str: str,
    last_triggered: datetime | None,
    current_time: datetime,
) -> bool:
    """Check if interval has passed since last triggered."""
    try:
        interval = parse_interval(interval_str)
    except ValueError:
        return True

    if last_triggered is None:
        return True

    elapsed = current_time - last_triggered
    return elapsed >= interval


def validate_cron_expression(cron_expr: str) -> bool:
    """Validate a cron expression."""
    try:
        from croniter import croniter

        croniter(cron_expr)
        return True
    except Exception:
        return False


def validate_interval_expression(interval_str: str) -> bool:
    """Validate an interval expression."""
    try:
        parse_interval(interval_str)
        return True
    except ValueError:
        return False


def get_next_run_time(rule: Rule, current_time: datetime | None = None) -> datetime | None:
    """Get the next scheduled run time for a rule."""
    if rule.schedule is None:
        return None

    if current_time is None:
        current_time = datetime.now(timezone.utc)

    tz = timezone.utc
    if rule.timezone and rule.timezone != "UTC":
        try:
            import pytz

            tz = pytz.timezone(rule.timezone)
        except Exception:
            pass

    local_time = current_time.astimezone(tz)

    if "cron" in rule.schedule:
        cron_expr = rule.schedule["cron"]
        try:
            from croniter import croniter

            cron = croniter(cron_expr, local_time)
            next_run = cron.get_next(datetime)
            if hasattr(next_run, "astimezone"):
                return next_run.astimezone(timezone.utc)
            return next_run.replace(tzinfo=tz).astimezone(timezone.utc)
        except Exception:
            return None

    elif "interval" in rule.schedule:
        interval_str = rule.schedule["interval"]
        try:
            interval = parse_interval(interval_str)
        except ValueError:
            return None

        if rule.last_triggered_at:
            next_time = rule.last_triggered_at + interval
            if next_time.tzinfo is None:
                next_time = next_time.replace(tzinfo=timezone.utc)
            return next_time.astimezone(timezone.utc)
        else:
            return current_time

    return None
