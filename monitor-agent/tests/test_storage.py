from __future__ import annotations

from pathlib import Path

import pytest

from core.models import Source, Action, Rule, TriggerLog
from core.storage import MonitorStorage
from datetime import datetime


def test_storage_init(tmp_db):
    assert tmp_db.get_all_sources() == []
    assert tmp_db.get_all_actions() == []
    assert tmp_db.get_all_rules() == []


def test_add_source(tmp_db, sample_source):
    tmp_db.add_source(sample_source)
    sources = tmp_db.get_all_sources()
    assert len(sources) == 1
    assert sources[0].id == sample_source.id
    assert sources[0].plugin == "youtube"


def test_add_action(tmp_db, sample_action):
    tmp_db.add_action(sample_action)
    actions = tmp_db.get_all_actions()
    assert len(actions) == 1
    assert actions[0].id == sample_action.id
    assert actions[0].name == "Test Action"


def test_add_rule(tmp_db, sample_rule):
    tmp_db.add_rule(sample_rule)
    rules = tmp_db.get_all_rules()
    assert len(rules) == 1
    assert rules[0].id == sample_rule.id
    assert rules[0].name == "Test Rule"


def test_get_source(tmp_db, sample_source):
    tmp_db.add_source(sample_source)
    source = tmp_db.get_source(sample_source.id)
    assert source is not None
    assert source.id == sample_source.id


def test_get_action(tmp_db, sample_action):
    tmp_db.add_action(sample_action)
    action = tmp_db.get_action(sample_action.id)
    assert action is not None
    assert action.id == sample_action.id


def test_get_rule(tmp_db, sample_rule):
    tmp_db.add_rule(sample_rule)
    rule = tmp_db.get_rule(sample_rule.id)
    assert rule is not None
    assert rule.id == sample_rule.id


def test_delete_source(tmp_db, sample_source):
    tmp_db.add_source(sample_source)
    tmp_db.delete_source(sample_source.id)
    assert tmp_db.get_all_sources() == []


def test_delete_action(tmp_db, sample_action):
    tmp_db.add_action(sample_action)
    tmp_db.delete_action(sample_action.id)
    assert tmp_db.get_all_actions() == []


def test_delete_rule(tmp_db, sample_rule):
    tmp_db.add_rule(sample_rule)
    tmp_db.delete_rule(sample_rule.id)
    assert tmp_db.get_all_rules() == []


def test_update_source_last_check(tmp_db, sample_source):
    tmp_db.add_source(sample_source)
    tmp_db.update_source_last_check(sample_source.id, "vid456")
    source = tmp_db.get_source(sample_source.id)
    assert source.last_item_id == "vid456"
    assert source.last_check is not None


def test_log_trigger(tmp_db, sample_rule, sample_action, sample_source):
    tmp_db.add_rule(sample_rule)
    tmp_db.add_action(sample_action)
    tmp_db.add_source(sample_source)

    log = TriggerLog(
        id="log123",
        rule_id=sample_rule.id,
        source_id=sample_source.id,
        action_id=sample_action.id,
        item_id="vid123",
        item_title="Test Video",
        item_url="https://youtube.com/watch?v=vid123",
        triggered_at=datetime.now(),
        exit_code=0,
        output="Success",
    )

    tmp_db.log_trigger(log)
    logs = tmp_db.get_trigger_logs()
    assert len(logs) == 1
    assert logs[0].id == "log123"


def test_get_trigger_logs_with_filter(tmp_db, sample_rule, sample_action, sample_source):
    tmp_db.add_rule(sample_rule)
    tmp_db.add_action(sample_action)
    tmp_db.add_source(sample_source)

    log1 = TriggerLog(
        id="log1",
        rule_id=sample_rule.id,
        source_id=sample_source.id,
        action_id=sample_action.id,
        item_id="vid1",
        item_title="Video 1",
        item_url="https://youtube.com/watch?v=vid1",
        triggered_at=datetime.now(),
        exit_code=0,
        output="OK",
    )

    log2 = TriggerLog(
        id="log2",
        rule_id="other-rule",
        source_id=sample_source.id,
        action_id=sample_action.id,
        item_id="vid2",
        item_title="Video 2",
        item_url="https://youtube.com/watch?v=vid2",
        triggered_at=datetime.now(),
        exit_code=1,
        output="Error",
    )

    tmp_db.log_trigger(log1)
    tmp_db.log_trigger(log2)

    logs_by_rule = tmp_db.get_trigger_logs(rule_id=sample_rule.id)
    assert len(logs_by_rule) == 1
    assert logs_by_rule[0].rule_id == sample_rule.id


def test_get_stats(tmp_db, sample_source, sample_action, sample_rule):
    tmp_db.add_source(sample_source)
    tmp_db.add_action(sample_action)
    tmp_db.add_rule(sample_rule)

    stats = tmp_db.get_stats()
    assert stats["sources_count"] == 1
    assert stats["actions_count"] == 1
    assert stats["rules_count"] == 1


def test_trigger_logs_with_limit(tmp_db, sample_rule, sample_action, sample_source):
    tmp_db.add_rule(sample_rule)
    tmp_db.add_action(sample_action)
    tmp_db.add_source(sample_source)

    for i in range(10):
        log = TriggerLog(
            id=f"log{i}",
            rule_id=sample_rule.id,
            source_id=sample_source.id,
            action_id=sample_action.id,
            item_id=f"vid{i}",
            item_title=f"Video {i}",
            item_url=f"https://youtube.com/watch?v=vid{i}",
            triggered_at=datetime.now(),
            exit_code=0,
            output="OK",
        )
        tmp_db.log_trigger(log)

    logs = tmp_db.get_trigger_logs(limit=5)
    assert len(logs) == 5
