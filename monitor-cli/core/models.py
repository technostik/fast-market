from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ItemMetadata:
    id: str
    title: str
    url: str
    published_at: datetime
    content_type: str
    source_plugin: str
    source_id: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Source:
    id: str
    plugin: str
    origin: str
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_check: datetime | None = None
    last_fetched_at: datetime | None = None
    last_item_id: str | None = None
    slowdown: int | None = None
    fallback_slowdown: int | None = None
    is_new: bool = True
    created_at: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class Action:
    id: str
    command: str
    description: str | None = None
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    last_run: datetime | None = None
    last_output: str | None = None
    last_exit_code: int | None = None


@dataclass(slots=True)
class Rule:
    id: str
    conditions: dict
    action_ids: list[str]
    on_error_action_ids: list[str] = field(default_factory=list)
    on_execution_action_ids: list[str] = field(default_factory=list)
    description: str | None = None
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    schedule: dict | None = None
    timezone: str = "UTC"
    last_triggered_at: datetime | None = None


@dataclass(slots=True)
class TriggerLog:
    id: str
    rule_id: str
    source_id: str
    action_id: str
    item_id: str
    item_title: str
    item_url: str
    triggered_at: datetime
    exit_code: int | None
    output: str | None
    item_extra: dict[str, Any] | None = None


@dataclass(slots=True)
class TriggerLogWithMetadata(TriggerLog):
    source_metadata: dict[str, Any] | None = None
    item_extra: dict[str, Any] | None = None


@dataclass(slots=True)
class RuleEvaluationResult:
    matched: bool
    failed_conditions: list[dict]


@dataclass(slots=True)
class RuleMismatchLog:
    id: str
    rule_id: str
    source_id: str
    item_id: str
    item_title: str
    failed_conditions: list[dict]
    evaluated_at: datetime


@dataclass(slots=True)
class RunErrorLog:
    id: str
    error_type: str  # fetch_error | plugin_not_found | action_not_found | action_exception | action_exit_error | output_contains_error
    message: str
    logged_at: datetime
    source_id: str | None = None
    action_id: str | None = None
    rule_id: str | None = None
    item_id: str | None = None
    item_title: str | None = None
    output: str | None = None
    trigger_log_id: str | None = None
