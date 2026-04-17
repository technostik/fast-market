"""Batch command utilities for field validation and helpers."""

from __future__ import annotations

import click


def get_nested_value(item: dict, field_path: str) -> any:
    """Get nested value using dot notation (e.g., 'original_comment.id').

    Args:
        item: Dictionary to get value from
        field_path: Field path with dots for nesting

    Returns:
        Value at path or None if not found
    """
    if "." not in field_path:
        return item.get(field_path)

    parts = field_path.split(".")
    value = item
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def validate_required_fields(
    data: list,
    required_fields: list[str],
    command_name: str,
    item_get_field: callable = None,
) -> None:
    """Validate that all items have required fields.

    Args:
        data: List of items to validate
        required_fields: List of required field names (supports dot notation like 'original_comment.id')
        command_name: Name of the command for error messages
        item_get_field: Optional function(item, field_name) -> value for custom field access

    Raises:
        click.ClickException: If any required field is missing
    """
    if not data:
        return

    for idx, item in enumerate(data, 1):
        for field in required_fields:
            value = None
            if item_get_field:
                value = item_get_field(item, field)
            else:
                value = get_nested_value(item, field)

            if value is None or value == "":
                raise click.ClickException(
                    f"Error: Missing required field '{field}' in item {idx}. "
                    f"Expected fields: {', '.join(required_fields)}"
                )


def get_field_with_fallback(item: dict, field: str, fallbacks: list[str] = None) -> str:
    """Get field value with fallback support.

    Args:
        item: Dictionary to get field from
        field: Primary field name
        fallbacks: List of fallback field names to try

    Returns:
        Field value or empty string if not found
    """
    value = get_nested_value(item, field)
    if value:
        return value

    if fallbacks:
        for fallback in fallbacks:
            value = get_nested_value(item, fallback)
            if value:
                return value

    return ""


def format_field_list(fields: list[str]) -> str:
    """Format field list for display in help text."""
    return ", ".join(fields)
