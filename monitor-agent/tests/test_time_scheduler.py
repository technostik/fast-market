from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.models import Rule
from core.time_scheduler import (
    parse_interval,
    parse_cron,
    parse_schedule,
    should_run_rule,
    validate_cron_expression,
    validate_interval_expression,
    get_next_run_time,
)


class TestParseInterval:
    """Tests for interval parsing."""

    def test_parse_seconds(self):
        result = parse_interval("30s")
        assert result == timedelta(seconds=30)

    def test_parse_minutes(self):
        result = parse_interval("5m")
        assert result == timedelta(minutes=5)

    def test_parse_hours(self):
        result = parse_interval("1h")
        assert result == timedelta(hours=1)

    def test_parse_days(self):
        result = parse_interval("1d")
        assert result == timedelta(days=1)

    def test_parse_large_value(self):
        result = parse_interval("24h")
        assert result == timedelta(hours=24)

    def test_parse_invalid_format(self):
        with pytest.raises(ValueError) as exc_info:
            parse_interval("invalid")
        assert "Invalid interval format" in str(exc_info.value)

    def test_parse_invalid_unit(self):
        with pytest.raises(ValueError) as exc_info:
            parse_interval("1x")
        assert "Invalid interval format" in str(exc_info.value)

    def test_parse_empty_string(self):
        with pytest.raises(ValueError):
            parse_interval("")


class TestParseCron:
    """Tests for cron expression parsing."""

    def test_parse_every_hour(self):
        result = parse_cron("0 * * * *")
        assert result["minute"] == "0"
        assert result["hour"] == "*"
        assert result["day"] == "*"
        assert result["month"] == "*"
        assert result["day_of_week"] == "*"

    def test_parse_daily(self):
        result = parse_cron("30 6 * * *")
        assert result["minute"] == "30"
        assert result["hour"] == "6"

    def test_parse_invalid_format(self):
        with pytest.raises(ValueError) as exc_info:
            parse_cron("0 0 0")
        assert "Expected 5 fields" in str(exc_info.value)

    def test_parse_invalid_expression(self):
        with pytest.raises(ValueError) as exc_info:
            parse_cron("99 * * * *")
        assert "Invalid cron expression" in str(exc_info.value)


class TestParseSchedule:
    """Tests for schedule dict parsing."""

    def test_parse_none(self):
        result = parse_schedule(None)
        assert result is None

    def test_parse_cron(self):
        result = parse_schedule({"cron": "0 * * * *"})
        assert result == "cron: 0 * * * *"

    def test_parse_interval(self):
        result = parse_schedule({"interval": "1h"})
        assert result == "interval: 1h"

    def test_parse_empty(self):
        result = parse_schedule({})
        assert result is None


class TestValidateExpressions:
    """Tests for validation functions."""

    def test_validate_cron_valid(self):
        assert validate_cron_expression("0 * * * *") is True
        assert validate_cron_expression("*/5 * * * *") is True
        assert validate_cron_expression("0 6 * * 1-5") is True

    def test_validate_cron_invalid(self):
        assert validate_cron_expression("invalid") is False
        assert validate_cron_expression("99 * * * *") is False
        assert validate_cron_expression("") is False

    def test_validate_interval_valid(self):
        assert validate_interval_expression("1s") is True
        assert validate_interval_expression("5m") is True
        assert validate_interval_expression("1h") is True
        assert validate_interval_expression("1d") is True

    def test_validate_interval_invalid(self):
        assert validate_interval_expression("invalid") is False
        assert validate_interval_expression("1x") is False
        assert validate_interval_expression("") is False


class TestShouldRunRule:
    """Tests for should_run_rule function."""

    def test_rule_without_schedule_always_runs(self):
        rule = Rule(
            id="test-rule",
            conditions={"all": []},
            action_ids=["action1"],
            schedule=None,
        )
        now = datetime.now(timezone.utc)
        assert should_run_rule(rule, now) is True

    def test_rule_with_schedule_first_run(self):
        rule = Rule(
            id="test-rule",
            conditions={"all": []},
            action_ids=["action1"],
            schedule={"interval": "1h"},
            last_triggered_at=None,
        )
        now = datetime.now(timezone.utc)
        assert should_run_rule(rule, now) is True

    def test_rule_with_interval_not_due(self):
        rule = Rule(
            id="test-rule",
            conditions={"all": []},
            action_ids=["action1"],
            schedule={"interval": "1h"},
            last_triggered_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        now = datetime.now(timezone.utc)
        assert should_run_rule(rule, now) is False

    def test_rule_with_interval_due(self):
        rule = Rule(
            id="test-rule",
            conditions={"all": []},
            action_ids=["action1"],
            schedule={"interval": "1h"},
            last_triggered_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        now = datetime.now(timezone.utc)
        assert should_run_rule(rule, now) is True


class TestGetNextRunTime:
    """Tests for get_next_run_time function."""

    def test_rule_without_schedule(self):
        rule = Rule(
            id="test-rule",
            conditions={"all": []},
            action_ids=["action1"],
            schedule=None,
        )
        result = get_next_run_time(rule)
        assert result is None

    def test_rule_with_interval(self):
        rule = Rule(
            id="test-rule",
            conditions={"all": []},
            action_ids=["action1"],
            schedule={"interval": "1h"},
            last_triggered_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        result = get_next_run_time(rule)
        assert result is not None
        assert result > datetime.now(timezone.utc)

    def test_rule_with_interval_no_previous_run(self):
        rule = Rule(
            id="test-rule",
            conditions={"all": []},
            action_ids=["action1"],
            schedule={"interval": "1h"},
            last_triggered_at=None,
        )
        result = get_next_run_time(rule)
        assert result is not None
