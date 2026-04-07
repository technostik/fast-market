from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, ConfigDict

from core.rule_engine import get_valid_condition_fields


class PluginType(str, Enum):
    YOUTUBE = "youtube"
    RSS = "rss"
    YT_SEARCH = "yt-search"


class ScheduleType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cron: str | None = None
    interval: str | None = None

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from core.time_scheduler import validate_cron_expression

        if not validate_cron_expression(v):
            raise ValueError(f"Invalid cron expression: {v}")
        return v

    @field_validator("interval")
    @classmethod
    def validate_interval(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from core.time_scheduler import validate_interval_expression

        if not validate_interval_expression(v):
            raise ValueError(f"Invalid interval expression: {v}")
        return v


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    plugin: PluginType
    origin: str = Field(min_length=1)
    description: str | None = None
    enabled: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)
    check_interval: int | None = None
    is_new: bool = True


class ActionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    command: str = Field(min_length=1)
    description: str | None = None
    enabled: bool = True


class RuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    conditions: str = Field(min_length=1)
    action_ids: list[str] = Field(min_length=1)
    description: str | None = None
    enabled: bool = True
    schedule: ScheduleType | None = None
    timezone: str = "UTC"


class MonitorConfig(BaseModel):
    default_check_interval: str | None = None
    seen_items_decay_days: int | None = Field(default=7, ge=1, le=365)
    sources: list[SourceConfig] = Field(default_factory=list)
    actions: list[ActionConfig] = Field(default_factory=list)
    rules: list[RuleConfig] = Field(default_factory=list)


class ConfigValidationError(Exception):
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        self.errors = errors
        self.warnings = warnings or []
        super().__init__("\n".join(errors))


KNOWN_SOURCE_FIELDS = {
    "id",
    "plugin",
    "origin",
    "description",
    "enabled",
    "metadata",
    "check_interval",
    "is_new",
}
KNOWN_ACTION_FIELDS = {"id", "command", "description", "enabled"}
KNOWN_RULE_FIELDS = {
    "id",
    "conditions",
    "action_ids",
    "description",
    "enabled",
    "schedule",
    "timezone",
}
KNOWN_SCHEDULE_FIELDS = {"cron", "interval"}
KNOWN_META_FIELDS = {"priority", "theme", "min_views", "max_results"}

VALID_CONDITION_FIELDS = get_valid_condition_fields()
VALID_PLACEHOLDERS = {
    "RULE_ID",
    "SOURCE_ID",
    "SOURCE_PLUGIN",
    "SOURCE_ORIGIN",
    "SOURCE_URL",
    "SOURCE_DESC",
    "ITEM_ID",
    "ITEM_TITLE",
    "ITEM_URL",
    "ITEM_CONTENT_TYPE",
    "ITEM_PUBLISHED",
}


def validate_config(
    config: dict[str, Any], plugin_manifests: dict[str, Any] | None = None
) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []

    if plugin_manifests is None:
        plugin_manifests = {}

    valid_plugins = set(plugin_manifests.keys()) | {p.value for p in PluginType}

    source_ids: set[str] = set()
    action_ids: set[str] = set()

    for i, source in enumerate(config.get("sources", [])):
        if "plugin" not in source:
            errors.append(f"Source #{i}: 'plugin' is required")
        elif source.get("plugin") not in valid_plugins:
            errors.append(
                f"Source #{i}: Unknown plugin '{source.get('plugin')}'. Available: {', '.join(sorted(valid_plugins))}"
            )

        if "origin" not in source or not source.get("origin"):
            errors.append(f"Source #{i}: 'origin' is required")
        elif (
            "plugin" in source
            and source["plugin"] in valid_plugins
            and source["plugin"] in plugin_manifests
        ):
            try:
                manifest = plugin_manifests.get(source["plugin"])
                if manifest and hasattr(manifest, "source_plugin_class"):
                    plugin_class = manifest.source_plugin_class
                    temp_config = plugin_class(
                        {"origin": source["origin"]}, {"origin": source["origin"]}
                    )
                    if not temp_config.validate_identifier(source["origin"]):
                        errors.append(
                            f"Source #{i}: Invalid origin '{source['origin']}' for plugin '{source['plugin']}'"
                        )
            except Exception as e:
                errors.append(f"Source #{i}: Error validating origin: {e}")

        unknown_fields = set(source.keys()) - KNOWN_SOURCE_FIELDS
        for field in unknown_fields:
            warnings.append(f"Source #{i}: Unknown field '{field}'")

        if "metadata" in source:
            unknown_meta = set(source["metadata"].keys()) - KNOWN_META_FIELDS
            for meta_key in unknown_meta:
                warnings.append(f"Source #{i}: Unknown metadata key '{meta_key}'")

        if "id" in source:
            src_id = source["id"]
            if src_id in source_ids:
                errors.append(f"Source #{i}: Duplicate id '{src_id}'")
            source_ids.add(src_id)

    for i, action in enumerate(config.get("actions", [])):
        unknown_fields = set(action.keys()) - KNOWN_ACTION_FIELDS
        for field in unknown_fields:
            warnings.append(f"Action #{i}: Unknown field '{field}'")

        if "id" in action:
            act_id = action["id"]
            if act_id in action_ids:
                errors.append(f"Action #{i}: Duplicate id '{act_id}'")
            action_ids.add(act_id)

        if "command" in action:
            unknown_placeholders = _find_unknown_placeholders(action["command"])
            for ph in unknown_placeholders:
                warnings.append(f"Action #{i}: Unknown placeholder '${ph}'")

    for i, rule in enumerate(config.get("rules", [])):
        unknown_fields = set(rule.keys()) - KNOWN_RULE_FIELDS
        for field in unknown_fields:
            warnings.append(f"Rule #{i}: Unknown field '{field}'")

        # Check required fields
        if "id" not in rule or not rule.get("id"):
            errors.append(f"Rule #{i}: 'id' is required")
        if "conditions" not in rule:
            errors.append(f"Rule #{i}: 'conditions' is required")
        if "action_ids" not in rule or not rule.get("action_ids"):
            errors.append(f"Rule #{i}: 'action_ids' is required")

        if "id" in rule:
            rule_id = rule["id"]
            if rule_id in source_ids:
                errors.append(f"Rule #{i}: id '{rule_id}' conflicts with source id")
            if rule_id in action_ids:
                errors.append(f"Rule #{i}: id '{rule_id}' conflicts with action id")

        if "action_ids" in rule:
            for aid in rule["action_ids"]:
                if aid not in action_ids:
                    errors.append(f"Rule #{i}: Action '{aid}' referenced but not defined")

        if "conditions" in rule:
            from core.rule_parser import RuleParser, RuleParseError

            conditions = rule["conditions"]
            
            # Handle boolean conditions: true = always match, false = never match
            if isinstance(conditions, bool):
                if conditions is False:
                    warnings.append(
                        f"Rule #{i}: 'conditions: false' will never match. "
                        f"Consider removing this rule or setting 'enabled: false'."
                    )
            elif not isinstance(conditions, str):
                errors.append(
                    f"Rule #{i}: 'conditions' must be a string DSL expression or boolean (true/false). "
                    f"Got {type(conditions).__name__}."
                )
            else:
                parser = RuleParser()
                try:
                    conditions_dict = parser.parse(conditions)
                    invalid_fields = _find_invalid_condition_fields(conditions_dict)
                    for field_info in invalid_fields:
                        warnings.append(f"Rule #{i}: Unknown condition field '{field_info}'")
                except RuleParseError as e:
                    errors.append(f"Rule #{i}: Invalid DSL condition: {e}")

        if "schedule" in rule and rule["schedule"]:
            schedule = rule["schedule"]
            # Handle both dict format ({cron: "0 * * * *"}) and string format ("0 * * * *")
            if isinstance(schedule, str):
                # String schedule is treated as cron expression
                from core.time_scheduler import validate_cron_expression

                if not validate_cron_expression(schedule):
                    errors.append(
                        f"Rule #{i}: Invalid cron expression in schedule: '{schedule}'. "
                        f"Use 'schedule: \"0 * * * *\"' for cron or 'schedule:\\n  cron: \"0 * * * *\"' for explicit format."
                    )
            elif isinstance(schedule, dict):
                unknown_schedule_fields = set(schedule.keys()) - KNOWN_SCHEDULE_FIELDS
                for field in unknown_schedule_fields:
                    warnings.append(f"Rule #{i}: Unknown schedule field '{field}'")
            else:
                errors.append(
                    f"Rule #{i}: Invalid schedule format. Expected cron string (e.g., 'schedule: \"0 * * * *\"') "
                    f"or dict with cron/interval (e.g., 'schedule:\\n  cron: \"0 * * * *\"')."
                )

    return errors, warnings


def _find_unknown_placeholders(command: str) -> set[str]:
    placeholder_pattern = re.compile(r"\$\{?([A-Z_][A-Z0-9_]*)\}?")
    placeholders = placeholder_pattern.findall(command)
    unknown = set()
    for ph in placeholders:
        if ph not in VALID_PLACEHOLDERS and not ph.startswith("EXTRA_"):
            unknown.add(ph)
    return unknown


def _find_invalid_condition_fields(conditions: dict) -> list[str]:
    invalid = []
    invalid_fields = _collect_invalid_fields(conditions)
    for field, path in invalid_fields:
        full_path = f"{path}.{field}" if path else field
        invalid.append(full_path)
    return invalid


def _collect_invalid_fields(group: dict, path: str = "") -> list[tuple[str, str]]:
    invalid = []
    if "all" in group:
        for cond in group["all"]:
            invalid.extend(_collect_invalid_fields(cond, path))
    elif "any" in group:
        for cond in group["any"]:
            invalid.extend(_collect_invalid_fields(cond, path))
    else:
        field = group.get("field", "")
        if field and not field.startswith("extra.") and field not in VALID_CONDITION_FIELDS:
            if "." in field:
                base_field = field.split(".")[0]
                if base_field != "extra" and base_field not in VALID_CONDITION_FIELDS:
                    invalid.append((field, path))
            else:
                invalid.append((field, path))
    return invalid


def parse_config(data: dict[str, Any]) -> MonitorConfig:
    return MonitorConfig(**data)


def get_config_template() -> str:
    return """# =============================================================================
# Monitor Agent Configuration
# =============================================================================
# This file is the source of truth. Run: monitor config sync
# =============================================================================

# =============================================================================
# GLOBAL SETTINGS
# =============================================================================
# default_check_interval: Default cooldown between fetches (e.g., '15m', '1h')
# seen_items_decay_days: Days to keep seen items history (default: 7, max: 365)
# =============================================================================
# default_check_interval: "15m"
# seen_items_decay_days: 7

# =============================================================================
# SOURCES
# =============================================================================
# Each source defines a feed to monitor.
#
# Required fields: id, plugin, origin
# Optional fields: description, enabled, metadata
#
# Available plugins: youtube, rss, yt-search
#   - youtube: origin = Channel ID (UC...), @handle, or channel URL
#   - rss: origin = RSS/Atom feed URL
#   - yt-search: origin = Search keywords
#
# Metadata options:
#   check_interval: 30s, 5m, 15m, 30m, 1h (default: 15m)
#   priority: 1-100
#   theme: string
#   min_views: integer (yt-search only)
#   max_results: integer (yt-search only)
# =============================================================================
sources:
  # - id: my_youtube_channel
  #   plugin: youtube
  #   origin: "@myhandle"
  #   description: "Monitor my channel"
  #   enabled: true
  #   metadata:
  #     check_interval: 15m
  #     priority: 50

# =============================================================================
# ACTIONS
# =============================================================================
# Actions are shell commands triggered when rules match.
#
# Required fields: id, command
# Optional fields: description, enabled
#
# Placeholders:
#   $RULE_ID, $SOURCE_ID, $SOURCE_PLUGIN, $SOURCE_ORIGIN, $SOURCE_URL, $SOURCE_DESC
#   $ITEM_ID, $ITEM_TITLE, $ITEM_URL, $ITEM_CONTENT_TYPE, $ITEM_PUBLISHED
#   $EXTRA_<FIELD> (any field from item's extra dict, uppercase)
# =============================================================================
actions:
  # - id: notify
  #   command: 'echo "New video: $ITEM_TITLE"'
  #   description: "Notify on new content"
  #   enabled: true

# =============================================================================
# RULES
# =============================================================================
# Rules define when to trigger actions based on item properties.
#
# Required fields: id, conditions, action_ids
# Optional fields: description, enabled, schedule, timezone
#
# DSL Condition Syntax:
#   Operators: ==, !=, >, <, >=, <=, contains, matches
#   Fields:
#     - Item: id, title, url, content_type, published_at
#     - Source: source_id, source_plugin, source_origin, source_description, source_metadata.*
#     - Extra: extra.* (any field from item's extra dict)
#   Logical: and, or, parentheses for grouping
#
# Schedule (optional):
#   cron: "0 * * * *" (minute hour day month weekday)
#   interval: 30s, 5m, 15m, 30m, 1h, 2h, 1d
# =============================================================================
rules:
  # - id: youtube_videos
  #   description: "Trigger on YouTube videos"
  #   enabled: true
  #   conditions: |
  #     source_plugin == 'youtube'
  #       and content_type == 'video'
  #       and extra.views > 10000
  #   action_ids: [notify]
  #   schedule:
  #     interval: 15m
  #   timezone: "UTC"
"""
