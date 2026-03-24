from __future__ import annotations

import pytest

from core.rule_formatter import RuleFormatter, RuleFormatError, format_rule_conditions
from core.rule_parser import RuleParser, RuleParseError


class TestRuleFormatter:
    """Tests for the DSL condition formatter."""

    def setup_method(self):
        self.formatter = RuleFormatter()

    def test_format_simple_condition(self):
        result = self.formatter.format(
            {"field": "content_type", "operator": "==", "value": "video"}
        )
        assert result == "content_type == 'video'"

    def test_format_and_conditions(self):
        conditions = {
            "all": [
                {"field": "content_type", "operator": "==", "value": "video"},
                {"field": "extra.duration", "operator": ">", "value": 600},
            ]
        }
        result = self.formatter.format(conditions)
        assert result == "content_type == 'video' and extra.duration > 600"

    def test_format_or_conditions(self):
        conditions = {
            "any": [
                {"field": "source_plugin", "operator": "==", "value": "youtube"},
                {"field": "source_plugin", "operator": "==", "value": "rss"},
            ]
        }
        result = self.formatter.format(conditions)
        assert result == "source_plugin == 'youtube' or source_plugin == 'rss'"

    def test_format_matches(self):
        conditions = {"all": [{"field": "title", "operator": "matches", "value": ".*python.*"}]}
        result = self.formatter.format(conditions)
        assert result == "title matches '.*python.*'"

    def test_format_contains(self):
        conditions = {"all": [{"field": "categories", "operator": "contains", "value": "tech"}]}
        result = self.formatter.format(conditions)
        assert result == "categories contains 'tech'"

    def test_format_numeric_values(self):
        conditions = {
            "all": [
                {"field": "duration", "operator": ">", "value": 600},
                {"field": "rating", "operator": ">=", "value": 4.5},
            ]
        }
        result = self.formatter.format(conditions)
        assert "duration > 600" in result
        assert "rating >= 4.5" in result

    def test_format_boolean_values(self):
        conditions = {"all": [{"field": "is_short", "operator": "==", "value": True}]}
        result = self.formatter.format(conditions)
        assert result == "is_short == true"

    def test_format_null_value(self):
        conditions = {"all": [{"field": "draft", "operator": "==", "value": None}]}
        result = self.formatter.format(conditions)
        assert result == "draft == null"

    def test_format_empty_string(self):
        conditions = {"all": [{"field": "title", "operator": "==", "value": ""}]}
        result = self.formatter.format(conditions)
        assert result == "title == ''"

    def test_format_with_parens(self):
        conditions = {
            "all": [
                {"field": "a", "operator": "==", "value": "1"},
                {"field": "b", "operator": "==", "value": "2"},
            ]
        }
        result = self.formatter.format_with_parens(conditions)
        assert "a == '1' and b == '2'" in result

    def test_format_nested_group(self):
        conditions = {
            "all": [
                {"field": "a", "operator": "==", "value": "1"},
                {
                    "any": [
                        {"field": "b", "operator": "==", "value": "2"},
                        {"field": "c", "operator": "==", "value": "3"},
                    ]
                },
            ]
        }
        result = self.formatter.format_with_parens(conditions)
        assert "a == '1'" in result
        assert "b == '2'" in result
        assert "c == '3'" in result

    def test_format_pretty(self):
        conditions = {
            "all": [
                {"field": "a", "operator": "==", "value": "1"},
                {"field": "b", "operator": "==", "value": "2"},
            ]
        }
        result = self.formatter.format(conditions, pretty=True)
        assert "a == '1'" in result
        assert "b == '2'" in result

    def test_format_special_characters_in_string(self):
        conditions = {"all": [{"field": "title", "operator": "==", "value": "it's cool"}]}
        result = self.formatter.format(conditions)
        assert "it\\'s cool" in result

    def test_format_convenience_function(self):
        conditions = {"all": [{"field": "content_type", "operator": "==", "value": "video"}]}
        result = format_rule_conditions(conditions)
        assert result == "content_type == 'video'"

    def test_format_dot_notation_field(self):
        conditions = {
            "all": [{"field": "source_metadata.theme", "operator": "==", "value": "tech"}]
        }
        result = self.formatter.format(conditions)
        assert result == "source_metadata.theme == 'tech'"


class TestRoundTrip:
    """Test round-trip parsing and formatting."""

    def setup_method(self):
        self.parser = RuleParser()
        self.formatter = RuleFormatter()

    def test_roundtrip_simple(self):
        dsl = "content_type == 'video'"
        parsed = self.parser.parse(dsl)
        formatted = self.formatter.format(parsed)
        reparsed = self.parser.parse(formatted)
        assert parsed == reparsed

    def test_roundtrip_and(self):
        dsl = "content_type == 'video' and duration > 600"
        parsed = self.parser.parse(dsl)
        formatted = self.formatter.format(parsed)
        reparsed = self.parser.parse(formatted)
        assert parsed == reparsed

    def test_roundtrip_or(self):
        dsl = "source == 'youtube' or source == 'rss'"
        parsed = self.parser.parse(dsl)
        formatted = self.formatter.format(parsed)
        reparsed = self.parser.parse(formatted)
        assert parsed == reparsed

    def test_roundtrip_nested(self):
        dsl = "(a == 1 and b == 2) or c == 3"
        parsed = self.parser.parse(dsl)
        formatted = self.formatter.format(parsed)
        reparsed = self.parser.parse(formatted)
        assert parsed == reparsed

    def test_roundtrip_complex(self):
        dsl = "(source == 'youtube' and (type == 'video' or type == 'short') and duration > 300) or (theme == 'tech' and title matches '.*AI.*')"
        parsed = self.parser.parse(dsl)
        formatted = self.formatter.format(parsed)
        reparsed = self.parser.parse(formatted)
        assert "any" in reparsed
        assert "all" in reparsed["any"][0]
