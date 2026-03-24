from __future__ import annotations

import re
from typing import Any


class RuleParseError(Exception):
    """Exception raised when DSL parsing fails."""

    def __init__(self, message: str, position: int | None = None):
        self.position = position
        if position is not None:
            super().__init__(f"Error at position {position}: {message}")
        else:
            super().__init__(message)


class RuleParser:
    """Parse DSL condition strings to internal rule format.

    Supported operators:
        ==, !=, >, <, >=, <=, contains, matches

    Supported logic:
        and, or, parentheses for grouping

    Example:
        parser = RuleParser()
        result = parser.parse("content_type == 'video' and extra.duration > 600")
        # Returns: {"all": [{"field": "content_type", "operator": "==", "value": "video"},
        #                  {"field": "extra.duration", "operator": ">", "value": 600}]}
    """

    OPERATORS = {"==", "!=", ">", "<", ">=", "<=", "contains", "matches"}
    LOGICAL_OPS = {"and", "or"}

    def parse(self, dsl_string: str) -> dict[str, list[dict]]:
        """Parse DSL string to internal condition format."""
        if not dsl_string or not dsl_string.strip():
            raise RuleParseError("Empty condition string")

        tokens = self._tokenize(dsl_string)
        if not tokens:
            raise RuleParseError("No tokens found in condition string")

        result = self._parse_expression(tokens, 0)

        if result.pos < len(tokens):
            remaining = " ".join(str(t) for t in tokens[result.pos :])
            raise RuleParseError(f"Unexpected tokens after expression: {remaining}")

        conditions = result.conditions
        if "all" not in conditions and "any" not in conditions:
            conditions = {"all": [conditions]}

        return conditions

    def _parse_expression(self, tokens: list, pos: int) -> _ParseResult:
        """Parse an expression (handles OR at top level)."""
        left = self._parse_and_group(tokens, pos)

        while left.pos < len(tokens) and self._is_logical_op(tokens[left.pos], "or"):
            left.pos += 1
            right = self._parse_and_group(tokens, left.pos)

            left_list = self._flatten_any(left.conditions)
            right_list = self._flatten_any(right.conditions)

            left = _ParseResult(
                conditions={"any": left_list + right_list},
                pos=right.pos,
            )

        return left

    def _flatten_any(self, conditions: dict) -> list:
        """Flatten nested 'any' conditions into a single list."""
        if "any" in conditions:
            result = []
            for c in conditions["any"]:
                result.extend(self._flatten_any(c))
            return result
        return [conditions]

    def _parse_and_group(self, tokens: list, pos: int) -> _ParseResult:
        """Parse an AND group (may be a single condition or parenthesized group)."""
        result = self._parse_condition_or_group(tokens, pos)

        while result.pos < len(tokens) and self._is_logical_op(tokens[result.pos], "and"):
            if "any" in result.conditions:
                conditions_list = [result.conditions]
            elif "all" in result.conditions:
                conditions_list = result.conditions["all"]
            else:
                conditions_list = [result.conditions]

            result.pos += 1
            next_cond = self._parse_condition_or_group(tokens, result.pos)

            if "any" in next_cond.conditions:
                conditions_list.append(next_cond.conditions)
                result.conditions = {"any": conditions_list}
            elif "all" in next_cond.conditions:
                conditions_list.extend(next_cond.conditions["all"])
                result.conditions = {"all": conditions_list}
            else:
                conditions_list.append(next_cond.conditions)
                result.conditions = {"all": conditions_list}

            result.pos = next_cond.pos

        return result

    def _parse_condition_or_group(self, tokens: list, pos: int) -> _ParseResult:
        """Parse a single condition or a parenthesized group."""
        if pos >= len(tokens):
            raise RuleParseError("Unexpected end of expression")

        token = tokens[pos]

        if token == "(":
            inner_result = self._parse_expression(tokens, pos + 1)
            if inner_result.pos >= len(tokens) or tokens[inner_result.pos] != ")":
                raise RuleParseError("Unclosed parenthesis")
            inner_result.pos += 1
            return inner_result

        return self._parse_single_condition(tokens, pos)

    def _parse_single_condition(self, tokens: list, pos: int) -> _ParseResult:
        """Parse a single condition: field operator value."""
        if pos >= len(tokens):
            raise RuleParseError("Expected field name")

        field = tokens[pos]
        if not isinstance(field, str) or field in self.OPERATORS or field in self.LOGICAL_OPS:
            raise RuleParseError(f"Expected field name, got: {field}")

        pos += 1
        if pos >= len(tokens):
            raise RuleParseError(f"Expected operator after field '{field}'")

        operator = tokens[pos]
        if operator not in self.OPERATORS:
            raise RuleParseError(
                f"Unknown operator: '{operator}'. Expected one of: {', '.join(self.OPERATORS)}"
            )

        pos += 1
        if pos >= len(tokens):
            raise RuleParseError(f"Expected value after operator '{operator}'")

        value = tokens[pos]
        parsed_value = self._parse_value(value)

        return _ParseResult(
            conditions={"field": field, "operator": operator, "value": parsed_value},
            pos=pos + 1,
        )

    def _parse_value(self, value: Any) -> Any:
        """Parse a value token to its proper type."""
        if isinstance(value, str):
            if value.startswith("'") and value.endswith("'"):
                return value[1:-1]
            if value.startswith('"') and value.endswith('"'):
                return value[1:-1]

            if value.lower() == "true":
                return True
            if value.lower() == "false":
                return False
            if value.lower() == "null" or value.lower() == "none":
                return None

            try:
                if "." in value:
                    return float(value)
                return int(value)
            except ValueError:
                return value

        return value

    def _tokenize(self, dsl_string: str) -> list:
        """Split DSL string into tokens, handling quotes and parentheses."""
        tokens = []
        i = 0
        length = len(dsl_string)

        while i < length:
            char = dsl_string[i]

            if char.isspace():
                i += 1
                continue

            if char == "(" or char == ")":
                tokens.append(char)
                i += 1
                continue

            if char == "'" or char == '"':
                quote = char
                j = i + 1
                while j < length:
                    if dsl_string[j] == quote and dsl_string[j - 1] != "\\":
                        break
                    j += 1
                if j >= length:
                    raise RuleParseError(f"Unclosed quote: {quote}", i)
                tokens.append(dsl_string[i : j + 1])
                i = j + 1
                continue

            if char in "<>=":
                if i + 1 < length and dsl_string[i + 1] == "=":
                    tokens.append(char + "=")
                    i += 2
                else:
                    tokens.append(char)
                    i += 1
                continue

            if char == "!":
                if i + 1 < length and dsl_string[i + 1] == "=":
                    tokens.append("!=")
                    i += 2
                else:
                    raise RuleParseError("Expected '=' after '!'", i)
                continue

            word_match = re.match(r"[a-zA-Z_][a-zA-Z0-9_.]*", dsl_string[i:])
            if word_match:
                word = word_match.group()
                tokens.append(word)
                i += len(word)
                continue

            number_match = re.match(r"-?\d+(\.\d+)?", dsl_string[i:])
            if number_match:
                tokens.append(number_match.group())
                i += len(number_match.group())
                continue

            i += 1

        return tokens

    def _is_logical_op(self, token: str, op: str) -> bool:
        """Check if token is the specified logical operator."""
        return token.lower() == op


class _ParseResult:
    """Result of parsing an expression."""

    def __init__(self, conditions: dict, pos: int):
        self.conditions = conditions
        self.pos = pos


def parse_condition(dsl_string: str) -> dict[str, list[dict]]:
    """Parse DSL condition string to internal format.

    This is a convenience function that creates a parser and parses the string.

    Args:
        dsl_string: DSL condition string (e.g., "content_type == 'video' and duration > 600")

    Returns:
        Internal condition dict with "all" or "any" keys

    Raises:
        RuleParseError: If the DSL string is invalid

    Example:
        >>> result = parse_condition("content_type == 'video' and duration > 600")
        >>> # Returns: {"all": [{"field": "content_type", "operator": "==", "value": "video"},
        ... #                  {"field": "duration", "operator": ">", "value": 600}]}
    """
    parser = RuleParser()
    return parser.parse(dsl_string)
