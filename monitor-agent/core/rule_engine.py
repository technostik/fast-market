from __future__ import annotations

import re
from typing import Any

from core.models import ItemMetadata, Rule, Source


def evaluate_rule(rule: Rule, item: ItemMetadata, source: Source) -> bool:
    """Evaluate if item matches rule conditions."""
    context = {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "published_at": item.published_at,
        "content_type": item.content_type,
        "source_plugin": item.source_plugin,
        "source_identifier": item.source_identifier,
        "source_description": source.description,
        **item.extra,
    }

    return _evaluate_condition_group(rule.conditions, context)


def _evaluate_condition_group(group: dict, context: dict) -> bool:
    """Handle AND/OR groups recursively."""
    if "all" in group:
        return all(_evaluate_condition_group(c, context) for c in group["all"])
    elif "any" in group:
        return any(_evaluate_condition_group(c, context) for c in group["any"])
    else:
        return _evaluate_single_condition(group, context)


def _evaluate_single_condition(cond: dict, context: dict) -> bool:
    """Evaluate a single condition against context."""
    field = cond["field"]
    operator = cond["operator"]
    expected = cond["value"]

    value = _get_nested_value(context, field)

    if operator == "==":
        return value == expected
    elif operator == "!=":
        return value != expected
    elif operator == ">":
        return value > expected
    elif operator == "<":
        return value < expected
    elif operator == ">=":
        return value >= expected
    elif operator == "<=":
        return value <= expected
    elif operator == "contains":
        if isinstance(value, (list, tuple)):
            return expected in value
        return expected in value
    elif operator == "matches":
        return bool(re.match(expected, str(value)))
    else:
        raise ValueError(f"Unknown operator: {operator}")


def _get_nested_value(context: dict, path: str) -> Any:
    """Get value using dot notation (e.g., 'extra.duration')."""
    parts = path.split(".")
    value = context
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = getattr(value, part, None)
        if value is None:
            break
    return value
