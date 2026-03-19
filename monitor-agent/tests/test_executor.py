from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.models import ItemMetadata, Source
from core.executor import execute_action
from core.models import Action


def test_executor_simple_echo(sample_item, sample_source):
    action = Action(
        id="echo-action",
        name="Echo Title",
        command='echo "$ITEM_TITLE"',
        description="Echo the item title",
    )

    code, output = execute_action(action, sample_item, sample_source, "Test Rule")
    assert code == 0
    assert sample_item.title in output


def test_executor_multiple_placeholders(sample_item, sample_source):
    action = Action(
        id="multi-action",
        name="Multi Placeholder",
        command='echo "$ITEM_TITLE - $ITEM_URL - $ITEM_CONTENT_TYPE"',
        description="Test multiple placeholders",
    )

    code, output = execute_action(action, sample_item, sample_source, "Test Rule")
    assert code == 0
    assert sample_item.title in output
    assert sample_item.url in output
    assert sample_item.content_type in output


def test_executor_rule_name_placeholder(sample_item, sample_source):
    action = Action(
        id="rule-action",
        name="Rule Name Test",
        command='echo "Rule: $RULE_NAME"',
        description="Test rule name placeholder",
    )

    code, output = execute_action(action, sample_item, sample_source, "My Custom Rule")
    assert code == 0
    assert "My Custom Rule" in output


def test_executor_thematic_placeholder(sample_item, sample_source):
    action = Action(
        id="thematic-action",
        name="Thematic Test",
        command='echo "Thematic: $THEMATIC"',
        description="Test THEMATIC placeholder",
    )

    code, output = execute_action(action, sample_item, sample_source, "Tech Videos")
    assert code == 0
    assert "Tech Videos" in output


def test_executor_source_placeholders(sample_item, sample_source):
    action = Action(
        id="source-action",
        name="Source Placeholders",
        command='echo "Plugin: $SOURCE_PLUGIN, Desc: $SOURCE_DESC"',
        description="Test source placeholders",
    )

    code, output = execute_action(action, sample_item, sample_source, "Test Rule")
    assert code == 0
    assert "$SOURCE_PLUGIN" not in output
    assert "youtube" in output


def test_executor_extra_placeholders(sample_item, sample_source):
    action = Action(
        id="extra-action",
        name="Extra Placeholders",
        command='echo "Duration: $EXTRA_DURATION_SECONDS, Channel: $EXTRA_CHANNEL_NAME"',
        description="Test extra placeholders",
    )

    code, output = execute_action(action, sample_item, sample_source, "Test Rule")
    assert code == 0
    assert "600" in output


def test_executor_non_braced_placeholders(sample_item, sample_source):
    action = Action(
        id="non-braced-action",
        name="Non Braced Placeholders",
        command="echo $ITEM_TITLE",
        description="Test non-braced placeholders",
    )

    code, output = execute_action(action, sample_item, sample_source, "Test Rule")
    assert code == 0
    assert sample_item.title in output


def test_executor_multiline_command(sample_item, sample_source):
    action = Action(
        id="multiline-action",
        name="Multiline Command",
        command="""echo "Title: $ITEM_TITLE"
echo "URL: $ITEM_URL"
echo "Done" """,
        description="Test multiline commands",
    )

    code, output = execute_action(action, sample_item, sample_source, "Test Rule")
    assert code == 0
    assert "Title:" in output
    assert "URL:" in output


def test_executor_failed_command(sample_item, sample_source):
    action = Action(
        id="fail-action",
        name="Failing Command",
        command="exit 1",
        description="Command that exits with 1",
    )

    code, output = execute_action(action, sample_item, sample_source, "Test Rule")
    assert code == 1
