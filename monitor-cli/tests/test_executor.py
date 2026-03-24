from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.models import ItemMetadata, Source
from core.executor import execute_action
from core.models import Action


def test_executor_simple_echo(sample_item, sample_source):
    action = Action(
        id="echo-action",
        command='echo "$ITEM_TITLE"',
        description="Echo the item title",
    )

    code, output, _ = execute_action(action, sample_item, sample_source, "test-rule-1")
    assert code == 0
    assert sample_item.title in output


def test_executor_multiple_placeholders(sample_item, sample_source):
    action = Action(
        id="multi-action",
        command='echo "$ITEM_TITLE - $ITEM_URL - $ITEM_CONTENT_TYPE"',
        description="Test multiple placeholders",
    )

    code, output, _ = execute_action(action, sample_item, sample_source, "test-rule-1")
    assert code == 0
    assert sample_item.title in output
    assert sample_item.url in output
    assert sample_item.content_type in output


def test_executor_rule_id_placeholder(sample_item, sample_source):
    action = Action(
        id="rule-action",
        command='echo "Rule: $RULE_ID"',
        description="Test rule ID placeholder",
    )

    code, output, _ = execute_action(action, sample_item, sample_source, "my-custom-rule")
    assert code == 0
    assert "my-custom-rule" in output


def test_executor_thematic_placeholder(sample_item, sample_source):
    action = Action(
        id="thematic-action",
        command='echo "Thematic: $RULE_ID"',
        description="Test RULE_ID placeholder",
    )

    code, output, _ = execute_action(action, sample_item, sample_source, "tech-videos")
    assert code == 0
    assert "tech-videos" in output


def test_executor_source_placeholders(sample_item, sample_source):
    action = Action(
        id="source-action",
        command='echo "Plugin: $SOURCE_PLUGIN, Desc: $SOURCE_DESC, Origin: $SOURCE_ORIGIN"',
        description="Test source placeholders",
    )

    code, output, _ = execute_action(action, sample_item, sample_source, "test-rule-1")
    assert code == 0
    assert "$SOURCE_PLUGIN" not in output
    assert "youtube" in output


def test_executor_extra_placeholders(sample_item, sample_source):
    action = Action(
        id="extra-action",
        command='echo "Duration: $EXTRA_DURATION_SECONDS, Channel: $EXTRA_CHANNEL_NAME"',
        description="Test extra placeholders",
    )

    code, output, _ = execute_action(action, sample_item, sample_source, "test-rule-1")
    assert code == 0
    assert "600" in output


def test_executor_non_braced_placeholders(sample_item, sample_source):
    action = Action(
        id="non-braced-action",
        command="echo $ITEM_TITLE",
        description="Test non-braced placeholders",
    )

    code, output, _ = execute_action(action, sample_item, sample_source, "test-rule-1")
    assert code == 0
    assert sample_item.title in output


def test_executor_multiline_command(sample_item, sample_source):
    action = Action(
        id="multiline-action",
        command="""echo "Title: $ITEM_TITLE"
echo "URL: $ITEM_URL"
echo "Done" """,
        description="Test multiline commands",
    )

    code, output, _ = execute_action(action, sample_item, sample_source, "test-rule-1")
    assert code == 0
    assert "Title:" in output
    assert "URL:" in output


def test_executor_failed_command(sample_item, sample_source):
    action = Action(
        id="fail-action",
        command="exit 1",
        description="Command that exits with 1",
    )

    code, output, _ = execute_action(action, sample_item, sample_source, "test-rule-1")
    assert code == 1
