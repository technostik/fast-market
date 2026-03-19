from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass(slots=True)
class ItemMetadata:
    """Metadata contract that ALL plugins must return."""

    id: str
    title: str
    url: str
    published_at: datetime
    content_type: str
    source_plugin: str
    source_identifier: str
    raw: dict | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Source:
    id: str
    plugin: str
    identifier: str
    description: str | None
    metadata: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    last_check: datetime | None = None
    last_fetched_at: datetime | None = None
    last_item_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class Action:
    id: str
    name: str
    command: str
    description: str | None
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    last_run: datetime | None = None
    last_output: str | None = None
    last_exit_code: int | None = None


@dataclass(slots=True)
class Rule:
    id: str
    name: str
    conditions: dict
    action_ids: list[str]
    enabled: bool = True
    description: str | None = None
    created_at: datetime = field(default_factory=datetime.now)


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
    source_metadata: dict[str, str] | None = None
    item_extra: dict[str, Any] | None = None
