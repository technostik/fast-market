from __future__ import annotations

import re
from typing import Any


class RuleFormatError(Exception):
    """Exception raised when formatting fails."""

    pass


class RuleFormatter:
    """Format internal condition dict to DSL string.

    Example:
        formatter = RuleFormatter()
        dsl = formatter.format({
            "all": [
                {"field": "content_type", "operator": "==", "value": "video"},
                {"field": "extra.duration", "operator": ">", "value": 600}
            ]
        })
        # Returns: "content_type == 'video' and extra.duration > 600"
    """

    def format(self, conditions: dict, pretty: bool = False) -> str:
        """Format condition dict to DSL string.

        Args:
            conditions: Internal condition dict with "all" or "any" keys
            pretty: If True, add newlines and indentation for readability

        Returns:
            DSL string representation

        Raises:
            RuleFormatError: If the condition format is invalid
        """
        if not conditions:
            return ""

        if "all" in conditions:
            parts = [self._format_item(c) for c in conditions["all"]]
            result = " and ".join(parts)
            if pretty and len(parts) > 2:
                return self._pretty_join(parts, "and", indent=0)
            return result

        if "any" in conditions:
            parts = [self._format_item(c) for c in conditions["any"]]
            result = " or ".join(parts)
            if pretty and len(parts) > 2:
                return self._pretty_join(parts, "or", indent=0)
            return result

        return self._format_condition(conditions)

    def _format_item(self, item: dict) -> str:
        """Format a single item which could be a condition or a group."""
        if "all" in item or "any" in item:
            return f"({self.format(item)})"
        return self._format_condition(item)

    def _format_condition(self, condition: dict) -> str:
        """Format a single condition to 'field operator value'."""
        field = condition.get("field", "")
        operator = condition.get("operator", "")
        value = condition.get("value", "")

        formatted_value = self._format_value(value)
        return f"{field} {operator} {formatted_value}"

    def _format_value(self, value: Any) -> str:
        """Format a value for DSL output."""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{escaped}'"
        if isinstance(value, list):
            return f"[{', '.join(self._format_value(v) for v in value)}]"
        return repr(value)

    def _needs_quoting(self, value: str) -> bool:
        """Check if a string value needs quoting."""
        if not value:
            return True
        if value.lower() in ("true", "false", "null", "none"):
            return True
        if not value[0].isalpha() and value[0] != "_":
            return True
        if re.search(r"\s", value):
            return True
        return False

    def _pretty_join(self, parts: list[str], operator: str, indent: int) -> str:
        """Join parts with operator and indentation for pretty printing."""
        sep = f" {operator} "
        base_indent = "    " * indent
        inner_indent = "    " * (indent + 1)

        if len(parts) <= 2:
            return sep.join(parts)

        lines = []
        for i, part in enumerate(parts):
            if i == 0:
                lines.append(part)
            elif i == len(parts) - 1:
                lines.append(f"{base_indent}{operator} {part}")
            else:
                lines.append(f"{base_indent}{operator} {part}")

        return f"\n{inner_indent}".join(lines)

    def format_with_parens(self, conditions: dict, level: int = 0) -> str:
        """Format condition with explicit parentheses for grouping.

        This is useful when you want to show the logical structure explicitly.
        """
        if not conditions:
            return ""

        if "all" in conditions:
            parts = []
            for c in conditions["all"]:
                if self._is_logical_group(c):
                    parts.append(f"({self.format_with_parens(c, level + 1)})")
                else:
                    parts.append(self._format_condition(c))
            return " and ".join(parts)

        if "any" in conditions:
            parts = []
            for c in conditions["any"]:
                if self._is_logical_group(c):
                    parts.append(f"({self.format_with_parens(c, level + 1)})")
                else:
                    parts.append(self._format_condition(c))
            return " or ".join(parts)

        return self._format_condition(conditions)

    def _is_logical_group(self, cond: dict) -> bool:
        """Check if a condition is a logical group (has "all" or "any")."""
        return "all" in cond or "any" in cond


def format_rule_conditions(conditions: dict, pretty: bool = False) -> str:
    """Format internal condition dict to DSL string.

    This is a convenience function that creates a formatter and formats the conditions.

    Args:
        conditions: Internal condition dict with "all" or "any" keys
        pretty: If True, add newlines and indentation for readability

    Returns:
        DSL string representation

    Example:
        >>> result = format_rule_conditions({"all": [{"field": "content_type", "operator": "==", "value": "video"}]})
        >>> # Returns: "content_type == 'video'"
    """
    formatter = RuleFormatter()
    return formatter.format(conditions, pretty)
