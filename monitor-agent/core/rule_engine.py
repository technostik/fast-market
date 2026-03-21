from __future__ import annotations

import re
from typing import Any

from core.models import ItemMetadata, Rule, RuleEvaluationResult, Source


VALID_FIELDS = {
    "id",
    "title",
    "url",
    "published_at",
    "content_type",
    "source_id",
    "source_plugin",
    "source_origin",
    "source_description",
    "source_metadata",
    "extra",
}


def evaluate_rule(rule: Rule, item: ItemMetadata, source: Source) -> bool:
    """Evaluate if item matches rule conditions."""
    context = _build_context(item, source)
    return _evaluate_condition_group(rule.conditions, context)


def evaluate_rule_with_details(
    rule: Rule, item: ItemMetadata, source: Source
) -> RuleEvaluationResult:
    """Evaluate rule and return detailed result including failed conditions."""
    context = _build_context(item, source)
    failed_conditions: list[dict] = []

    _evaluate_condition_group_with_details(rule.conditions, context, failed_conditions)

    matched = len(failed_conditions) == 0
    return RuleEvaluationResult(matched=matched, failed_conditions=failed_conditions)


def _build_context(item: ItemMetadata, source: Source) -> dict[str, Any]:
    """Build evaluation context from item and source."""
    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "published_at": item.published_at,
        "content_type": item.content_type,
        "source_id": item.source_id,
        "source_plugin": item.source_plugin,
        "source_origin": source.origin,
        "source_description": source.description,
        "source_metadata": source.metadata,
        "extra": item.extra,
        **item.extra,
    }


def _evaluate_condition_group(group: dict, context: dict) -> bool:
    """Handle AND/OR groups recursively."""
    if "all" in group:
        return all(_evaluate_condition_group(c, context) for c in group["all"])
    elif "any" in group:
        return any(_evaluate_condition_group(c, context) for c in group["any"])
    else:
        return _evaluate_single_condition(group, context)


def _evaluate_condition_group_with_details(
    group: dict, context: dict, failed_conditions: list[dict]
) -> bool:
    """Handle AND/OR groups recursively, collecting failed conditions."""
    if "all" in group:
        all_passed = True
        for cond in group["all"]:
            if not _evaluate_single_condition_with_details(cond, context, failed_conditions):
                all_passed = False
        return all_passed
    elif "any" in group:
        any_passed = False
        for cond in group["any"]:
            if _evaluate_single_condition_with_details(cond, context, failed_conditions):
                any_passed = True
        if not any_passed:
            failed_conditions.extend(group["any"])
        return any_passed
    else:
        if not _evaluate_single_condition_with_details(group, context, failed_conditions):
            failed_conditions.append(group)
        return len([c for c in failed_conditions if c == group]) == 0


def _evaluate_single_condition(cond: dict, context: dict) -> bool:
    """Evaluate a single condition against context."""
    return _evaluate_single_condition_impl(cond, context)[0]


def _evaluate_single_condition_with_details(
    cond: dict, context: dict, failed_conditions: list[dict]
) -> bool:
    """Evaluate a single condition and add to failed list if it doesn't match."""
    matched, actual_value, reason = _evaluate_single_condition_impl(cond, context)
    if not matched:
        field = cond["field"]
        operator = cond["operator"]
        expected = cond["value"]
        failed_conditions.append(
            {
                "field": field,
                "operator": operator,
                "expected": expected,
                "actual": actual_value,
                "reason": reason,
            }
        )
    return matched


def _evaluate_single_condition_impl(cond: dict, context: dict) -> tuple[bool, Any, str]:
    """Evaluate a single condition. Returns (matched, actual_value, reason)."""
    field = cond["field"]
    operator = cond["operator"]
    expected = cond["value"]

    value = _get_nested_value(context, field)

    if value is None:
        if operator == "==":
            matched = expected is None
            return (
                matched,
                None,
                f"field is None, expected {'None' if expected is None else repr(expected)}",
            )
        elif operator == "!=":
            matched = expected is not None
            return matched, None, f"field is None, expected not None"
        return False, None, "field is None, comparison not possible"

    if operator == "==":
        matched = value == expected
        return matched, value, f"expected {repr(expected)}, got {repr(value)}"
    elif operator == "!=":
        matched = value != expected
        return matched, value, f"expected != {repr(expected)}, got {repr(value)}"
    elif operator == ">":
        matched = value > expected
        return matched, value, f"expected > {repr(expected)}, got {repr(value)}"
    elif operator == "<":
        matched = value < expected
        return matched, value, f"expected < {repr(expected)}, got {repr(value)}"
    elif operator == ">=":
        matched = value >= expected
        return matched, value, f"expected >= {repr(expected)}, got {repr(value)}"
    elif operator == "<=":
        matched = value <= expected
        return matched, value, f"expected <= {repr(expected)}, got {repr(value)}"
    elif operator == "contains":
        if isinstance(value, (list, tuple)):
            matched = expected in value
        else:
            matched = expected in value
        return matched, value, f"expected {repr(expected)} in {repr(value)}"
    elif operator == "matches":
        matched = bool(re.match(expected, str(value)))
        return matched, value, f"expected pattern {repr(expected)}, got {repr(value)}"
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


def get_valid_condition_fields() -> set[str]:
    """Return set of valid field names for conditions."""
    return VALID_FIELDS.copy()
