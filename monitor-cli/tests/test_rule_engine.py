from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.models import ItemMetadata, Rule, Source
from core.rule_engine import evaluate_rule


def test_youtube_short_rule(sample_rule, sample_item, sample_source):
    rule = Rule(
        id="short-rule",
        conditions={
            "all": [
                {"field": "source_plugin", "operator": "==", "value": "youtube"},
                {"field": "is_short", "operator": "==", "value": True},
            ]
        },
        action_ids=["action1"],
    )

    short_item = ItemMetadata(
        id="short123",
        title="Test Short",
        url="https://youtube.com/shorts/short123",
        published_at=datetime.now(timezone.utc),
        content_type="short",
        source_plugin="youtube",
        source_id="src1",
        extra={"is_short": True, "duration_seconds": 45},
    )

    source = Source(id="src1", plugin="youtube", origin="UC123", description="Test Channel")

    assert evaluate_rule(rule, short_item, source) is True


def test_long_video_rule_not_matched(sample_rule, sample_item, sample_source):
    rule = Rule(
        id="long-rule",
        conditions={
            "all": [
                {"field": "source_plugin", "operator": "==", "value": "youtube"},
                {"field": "duration_seconds", "operator": ">=", "value": 600},
            ]
        },
        action_ids=["action1"],
    )

    assert evaluate_rule(rule, sample_item, sample_source) is True

    short_item = ItemMetadata(
        id="vid456",
        title="Short Video",
        url="https://youtube.com/watch?v=vid456",
        published_at=datetime.now(timezone.utc),
        content_type="video",
        source_plugin="youtube",
        source_id="src1",
        extra={"is_short": False, "duration_seconds": 300},
    )

    assert evaluate_rule(rule, short_item, sample_source) is False


def test_or_conditions(sample_rule, sample_item, sample_source):
    rule = Rule(
        id="or-rule",
        conditions={
            "any": [
                {"field": "content_type", "operator": "==", "value": "short"},
                {"field": "title", "operator": "contains", "value": "Tutorial"},
            ]
        },
        action_ids=["action1"],
    )

    short_item = ItemMetadata(
        id="vid789",
        title="Quick Tip",
        url="https://youtube.com/shorts/vid789",
        published_at=datetime.now(timezone.utc),
        content_type="short",
        source_plugin="youtube",
        source_id="src1",
        extra={"is_short": True},
    )

    assert evaluate_rule(rule, short_item, sample_source) is True

    tutorial_item = ItemMetadata(
        id="vid999",
        title="Python Tutorial",
        url="https://youtube.com/watch?v=vid999",
        published_at=datetime.now(timezone.utc),
        content_type="video",
        source_plugin="youtube",
        source_id="src1",
        extra={"is_short": False},
    )

    assert evaluate_rule(rule, tutorial_item, sample_source) is True


def test_nested_conditions(sample_rule, sample_item, sample_source):
    rule = Rule(
        id="nested-rule",
        conditions={
            "all": [
                {"field": "source_plugin", "operator": "==", "value": "youtube"},
                {
                    "any": [
                        {"field": "content_type", "operator": "==", "value": "short"},
                        {"field": "channel_name", "operator": "contains", "value": "Tech"},
                    ]
                },
            ]
        },
        action_ids=["action1"],
    )

    channeled_item = ItemMetadata(
        id="vid111",
        title="Tech Review",
        url="https://youtube.com/watch?v=vid111",
        published_at=datetime.now(timezone.utc),
        content_type="video",
        source_plugin="youtube",
        source_id="src1",
        extra={"is_short": False, "channel_name": "Tech Reviews"},
    )

    assert evaluate_rule(rule, channeled_item, sample_source) is True


def test_regex_matching(sample_rule, sample_item, sample_source):
    rule = Rule(
        id="regex-rule",
        conditions={
            "all": [{"field": "title", "operator": "matches", "value": r".*(AI|ML|MLOps).*"}]
        },
        action_ids=["action1"],
    )

    ai_item = ItemMetadata(
        id="vid222",
        title="Introduction to AI",
        url="https://youtube.com/watch?v=vid222",
        published_at=datetime.now(timezone.utc),
        content_type="video",
        source_plugin="youtube",
        source_id="src1",
        extra={},
    )

    assert evaluate_rule(rule, ai_item, sample_source) is True

    other_item = ItemMetadata(
        id="vid333",
        title="Cooking Tutorial",
        url="https://youtube.com/watch?v=vid333",
        published_at=datetime.now(timezone.utc),
        content_type="video",
        source_plugin="youtube",
        source_id="src1",
        extra={},
    )

    assert evaluate_rule(rule, other_item, sample_source) is False


def test_inequality_operators(sample_rule, sample_item, sample_source):
    rule = Rule(
        id="neq-rule",
        conditions={"all": [{"field": "content_type", "operator": "!=", "value": "short"}]},
        action_ids=["action1"],
    )

    assert evaluate_rule(rule, sample_item, sample_source) is True


def test_comparison_operators(sample_rule, sample_item, sample_source):
    rule_gte = Rule(
        id="gte-rule",
        conditions={"all": [{"field": "duration_seconds", "operator": ">=", "value": 600}]},
        action_ids=["action1"],
    )

    assert evaluate_rule(rule_gte, sample_item, sample_source) is True

    rule_lte = Rule(
        id="lte-rule",
        conditions={"all": [{"field": "duration_seconds", "operator": "<=", "value": 600}]},
        action_ids=["action1"],
    )

    assert evaluate_rule(rule_lte, sample_item, sample_source) is True


def test_rss_article_rule(sample_rule, sample_item, sample_source):
    rss_source = Source(
        id="rss-src",
        plugin="rss",
        origin="https://example.com/feed.xml",
        description="Tech Blog",
    )

    rule = Rule(
        id="rss-rule",
        conditions={
            "all": [
                {"field": "source_plugin", "operator": "==", "value": "rss"},
                {"field": "categories", "operator": "contains", "value": "technology"},
            ]
        },
        action_ids=["action1"],
    )

    article = ItemMetadata(
        id="art123",
        title="Latest Tech News",
        url="https://example.com/article123",
        published_at=datetime.now(timezone.utc),
        content_type="article",
        source_plugin="rss",
        source_id="rss-src",
        extra={"categories": ["technology", "news"], "author": "John Doe", "word_count": 500},
    )

    assert evaluate_rule(rule, article, rss_source) is True
