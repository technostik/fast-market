from __future__ import annotations

import pytest

from core.rule_parser import RuleParser, RuleParseError, parse_condition


class TestRuleParser:
    """Tests for the DSL condition parser."""

    def setup_method(self):
        self.parser = RuleParser()

    def test_simple_equality(self):
        result = self.parser.parse("content_type == 'video'")
        assert result == {"all": [{"field": "content_type", "operator": "==", "value": "video"}]}

    def test_simple_greater_than(self):
        result = self.parser.parse("extra.duration > 600")
        assert result == {"all": [{"field": "extra.duration", "operator": ">", "value": 600}]}

    def test_simple_less_than(self):
        result = self.parser.parse("extra.duration < 60")
        assert result == {"all": [{"field": "extra.duration", "operator": "<", "value": 60}]}

    def test_simple_matches(self):
        result = self.parser.parse("title matches '.*python.*'")
        assert result == {"all": [{"field": "title", "operator": "matches", "value": ".*python.*"}]}

    def test_simple_not_equals(self):
        result = self.parser.parse("source_metadata.theme != 'gaming'")
        assert result == {
            "all": [{"field": "source_metadata.theme", "operator": "!=", "value": "gaming"}]
        }

    def test_simple_gte(self):
        result = self.parser.parse("extra.views >= 1000")
        assert result == {"all": [{"field": "extra.views", "operator": ">=", "value": 1000}]}

    def test_simple_lte(self):
        result = self.parser.parse("extra.word_count <= 500")
        assert result == {"all": [{"field": "extra.word_count", "operator": "<=", "value": 500}]}

    def test_simple_contains(self):
        result = self.parser.parse("extra.categories contains 'technology'")
        assert result == {
            "all": [{"field": "extra.categories", "operator": "contains", "value": "technology"}]
        }

    def test_and_conditions(self):
        result = self.parser.parse("content_type == 'video' and extra.duration > 600")
        assert result == {
            "all": [
                {"field": "content_type", "operator": "==", "value": "video"},
                {"field": "extra.duration", "operator": ">", "value": 600},
            ]
        }

    def test_or_conditions(self):
        result = self.parser.parse("source_plugin == 'youtube' or source_plugin == 'rss'")
        assert result == {
            "any": [
                {"field": "source_plugin", "operator": "==", "value": "youtube"},
                {"field": "source_plugin", "operator": "==", "value": "rss"},
            ]
        }

    def test_parentheses_grouping(self):
        result = self.parser.parse(
            "(content_type == 'video' and extra.duration > 600) or source_metadata.priority == 'high'"
        )
        assert result == {
            "any": [
                {
                    "all": [
                        {"field": "content_type", "operator": "==", "value": "video"},
                        {"field": "extra.duration", "operator": ">", "value": 600},
                    ]
                },
                {"field": "source_metadata.priority", "operator": "==", "value": "high"},
            ]
        }

    def test_complex_nested_conditions(self):
        dsl = "(source_plugin == 'youtube' and (content_type == 'video' or content_type == 'short') and extra.duration > 300) or (source_metadata.theme == 'technology' and title matches '.*AI.*')"
        result = self.parser.parse(dsl)
        assert "any" in result
        assert len(result["any"]) == 2

    def test_double_quoted_string(self):
        result = self.parser.parse('content_type == "video"')
        assert result == {"all": [{"field": "content_type", "operator": "==", "value": "video"}]}

    def test_boolean_true(self):
        result = self.parser.parse("extra.is_short == true")
        assert result == {"all": [{"field": "extra.is_short", "operator": "==", "value": True}]}

    def test_boolean_false(self):
        result = self.parser.parse("extra.is_short == false")
        assert result == {"all": [{"field": "extra.is_short", "operator": "==", "value": False}]}

    def test_number_value(self):
        result = self.parser.parse("extra.count > 100")
        assert result == {"all": [{"field": "extra.count", "operator": ">", "value": 100}]}

    def test_float_value(self):
        result = self.parser.parse("extra.rating >= 4.5")
        assert result == {"all": [{"field": "extra.rating", "operator": ">=", "value": 4.5}]}

    def test_negative_number(self):
        result = self.parser.parse("extra.offset > -10")
        assert result == {"all": [{"field": "extra.offset", "operator": ">", "value": -10}]}

    def test_null_value(self):
        result = self.parser.parse("extra.draft == null")
        assert result == {"all": [{"field": "extra.draft", "operator": "==", "value": None}]}

    def test_empty_string(self):
        result = self.parser.parse("extra.title == ''")
        assert result == {"all": [{"field": "extra.title", "operator": "==", "value": ""}]}

    def test_dot_notation_field(self):
        result = self.parser.parse("source_metadata.theme == 'tech'")
        assert result == {
            "all": [{"field": "source_metadata.theme", "operator": "==", "value": "tech"}]
        }

    def test_whitespace_handling(self):
        result = self.parser.parse("  content_type  ==  'video'  ")
        assert result == {"all": [{"field": "content_type", "operator": "==", "value": "video"}]}

    def test_multiple_and(self):
        result = self.parser.parse("a == 1 and b == 2 and c == 3")
        assert "all" in result
        assert len(result["all"]) == 3

    def test_multiple_or(self):
        result = self.parser.parse("a == 1 or b == 2 or c == 3")
        assert "any" in result
        assert len(result["any"]) == 3

    def test_mixed_and_or(self):
        result = self.parser.parse("a == 1 and b == 2 or c == 3")
        assert "any" in result

    def test_deep_nesting(self):
        result = self.parser.parse("(a == 1 and (b == 2 and (c == 3)))")
        assert "all" in result
        assert len(result["all"]) == 3

    def test_parse_convenience_function(self):
        result = parse_condition("content_type == 'video'")
        assert result == {"all": [{"field": "content_type", "operator": "==", "value": "video"}]}

    def test_error_empty_string(self):
        with pytest.raises(RuleParseError):
            self.parser.parse("")

    def test_error_unclosed_quote(self):
        with pytest.raises(RuleParseError) as exc_info:
            self.parser.parse("content_type == 'video")
        assert "Unclosed quote" in str(exc_info.value)

    def test_error_unclosed_parenthesis(self):
        with pytest.raises(RuleParseError) as exc_info:
            self.parser.parse("(content_type == 'video'")
        assert "Unclosed parenthesis" in str(exc_info.value)

    def test_error_unknown_operator(self):
        with pytest.raises(RuleParseError) as exc_info:
            self.parser.parse("content_type = 'video'")
        assert "Unknown operator" in str(exc_info.value)

    def test_error_missing_value(self):
        with pytest.raises(RuleParseError) as exc_info:
            self.parser.parse("content_type == ")
        assert "Expected value" in str(exc_info.value)

    def test_error_trailing_operator(self):
        with pytest.raises(RuleParseError) as exc_info:
            self.parser.parse("content_type == 'video' and")
        assert "Unexpected end of expression" in str(exc_info.value)
