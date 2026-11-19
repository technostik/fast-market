from __future__ import annotations

import pytest
from click.testing import CliRunner

import commands.targets.register as targets_reg
from common.message_targets import (
    TargetError,
    list_targets,
    normalize_chat_ref,
    normalize_targets,
    resolve_target,
    slugify_target_id,
    unique_target_id,
    validate_target_id,
)
from core.targets import merge_discovered


def test_validate_target_id_normalizes_and_rejects():
    assert validate_target_id(" Joriel ") == "joriel"
    with pytest.raises(TargetError):
        validate_target_id("bad id!")


def test_normalize_targets_validates_chat_ids():
    targets = normalize_targets(
        {
            "targets": {
                "joriel": {"chat_id": 255925597, "label": "DM"},
                "tech": {"chat_id": "-100123", "type": "channel"},
            }
        }
    )
    assert targets["joriel"]["chat_id"] == 255925597
    assert targets["tech"]["chat_id"] == -100123
    assert targets["tech"]["label"] == "tech"
    with pytest.raises(TargetError):
        normalize_targets({"targets": {"x": {}}})
    with pytest.raises(TargetError):
        normalize_targets({"targets": {"x": {"chat_id": "abc"}}})


def test_resolve_named_and_raw_targets():
    cfg = {"targets": {"joriel": {"chat_id": 1}, "tech": {"chat_id": -2}}}
    assert resolve_target(cfg, "JORIEL") == ("joriel", 1)
    assert resolve_target(cfg, "-123") == ("-123", -123)


def test_resolve_default_then_legacy_then_single():
    cfg = {"targets": {"joriel": {"chat_id": 1}, "tech": {"chat_id": -2}}}
    assert resolve_target({**cfg, "default_target": "tech"}) == ("tech", -2)
    # legacy allowed_chat_id matching a named target selects that target
    assert resolve_target({**cfg, "allowed_chat_id": -2}) == ("tech", -2)
    # a single target is unambiguous
    assert resolve_target({"targets": {"only": {"chat_id": 9}}}) == ("only", 9)
    with pytest.raises(TargetError):
        resolve_target(cfg)


def test_resolve_legacy_only_and_unknown_explicit_target():
    assert resolve_target({"allowed_chat_id": 42}) == ("allowed_chat_id", 42)
    with pytest.raises(TargetError):
        resolve_target({"allowed_chat_id": 42}, "nope")
    with pytest.raises(TargetError):
        resolve_target({})


def test_list_targets_marks_default_and_legacy():
    rows = list_targets(
        {
            "targets": {"joriel": {"chat_id": 1, "label": "DM"}},
            "default_target": "joriel",
        }
    )
    assert rows == [
        {"id": "joriel", "chat_id": 1, "label": "DM", "type": "", "is_default": True}
    ]
    legacy = list_targets({"allowed_chat_id": 7})
    assert legacy[0]["id"] == "allowed_chat_id"
    assert legacy[0]["is_default"] is True
    mixed = list_targets({"targets": {"t": {"chat_id": 1}}, "allowed_chat_id": 2})
    assert [row["id"] for row in mixed] == ["t", "allowed_chat_id"]


def test_slug_and_unique_ids():
    assert slugify_target_id("@Tech Nostik") == "tech_nostik"
    assert unique_target_id("tech", {"tech": {}, "tech_2": {}}) == "tech_3"
    assert unique_target_id("", {}) == "target"


def test_merge_discovered_adds_updates_and_dedupes():
    existing = {"joriel": {"chat_id": 1, "label": "DM", "type": "private"}}
    chats = [
        {"chat_id": 1, "title": "Johann", "username": "joriel", "type": "private"},
        {"chat_id": -100, "title": "Tech Nostik", "username": "", "type": "channel"},
        {"chat_id": -200, "title": "", "username": "", "type": "group"},
    ]
    merged, added, updated = merge_discovered(existing, chats)

    assert updated == ["joriel"]
    assert merged["joriel"]["label"] == "Johann"
    assert added == ["tech_nostik", "chat_200"]
    assert merged["tech_nostik"]["chat_id"] == -100
    assert merged["chat_200"]["chat_id"] == -200

    # Discovering the same chat again updates, never duplicates.
    merged2, added2, updated2 = merge_discovered(merged, chats)
    assert added2 == []
    assert set(updated2) == {"joriel", "tech_nostik", "chat_200"}
    assert merged2.keys() == merged.keys()


def test_targets_cli_add_without_type(tmp_path, monkeypatch):
    path = tmp_path / "message.yaml"
    monkeypatch.setattr(targets_reg, "_config_path", lambda: path)
    group = targets_reg.register({}).click_command

    result = CliRunner().invoke(
        group, ["add", "technostik", "--chat-id", "-100123", "--label", "Tech"]
    )
    assert result.exit_code == 0, result.output
    assert "Target 'technostik' added" in result.output

    import yaml

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["telegram"]["targets"]["technostik"] == {
        "chat_id": -100123,
        "label": "Tech",
    }
    # The first target becomes the default so a bare `message alert` works.
    assert saved["telegram"]["default_target"] == "technostik"


def test_targets_cli_duplicate_is_an_error(tmp_path, monkeypatch):
    path = tmp_path / "message.yaml"
    monkeypatch.setattr(targets_reg, "_config_path", lambda: path)
    group = targets_reg.register({}).click_command
    runner = CliRunner()
    assert runner.invoke(group, ["add", "x", "--chat-id", "1"]).exit_code == 0
    result = runner.invoke(group, ["add", "x", "--chat-id", "2"])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_normalize_chat_ref_accepts_ids_usernames_and_links():
    assert normalize_chat_ref("-1001234567890") == -1001234567890
    assert normalize_chat_ref("@Tech_Nostik") == "@Tech_Nostik"
    assert normalize_chat_ref("technostik") == "@technostik"
    assert normalize_chat_ref("https://t.me/technostik") == "@technostik"
    assert normalize_chat_ref("t.me/s/technostik?utm=1") == "@technostik"
    with pytest.raises(TargetError):
        normalize_chat_ref("https://t.me/+privateInvite")
    with pytest.raises(TargetError):
        normalize_chat_ref("a")


class _FakeTelegram:
    name = "telegram"

    def __init__(self, info=None, chats=None):
        self._info = info or {}
        self._chats = chats or []

    def resolve_chat_info(self, ref):
        return self._info

    def discover_chats(self, wait=0):
        return self._chats


def _isolated_group(tmp_path, monkeypatch, fake):
    path = tmp_path / "message.yaml"
    monkeypatch.setattr(targets_reg, "_config_path", lambda: path)
    monkeypatch.setattr(targets_reg, "load_config", lambda: {"telegram": {}})
    monkeypatch.setattr(targets_reg, "build_plugin", lambda cfg, src: fake)
    return targets_reg.register({}).click_command, path


def test_targets_cli_add_by_username_resolves_id(tmp_path, monkeypatch):
    fake = _FakeTelegram(
        info={
            "chat_id": -1009876543210,
            "title": "Tech Nostik",
            "username": "technostik",
            "type": "channel",
        }
    )
    group, path = _isolated_group(tmp_path, monkeypatch, fake)

    result = CliRunner().invoke(
        group, ["add", "technostik", "--username", "https://t.me/technostik"]
    )
    assert result.exit_code == 0, result.output
    assert "chat_id=-1009876543210 [channel]" in result.output

    import yaml

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["telegram"]["targets"]["technostik"] == {
        "chat_id": -1009876543210,
        "label": "Tech Nostik",
        "type": "channel",
    }


def test_targets_cli_discover_by_chat_writes_target(tmp_path, monkeypatch):
    fake = _FakeTelegram(
        info={
            "chat_id": -100111,
            "title": "Tech Nostik",
            "username": "technostik",
            "type": "channel",
        }
    )
    group, path = _isolated_group(tmp_path, monkeypatch, fake)

    result = CliRunner().invoke(group, ["discover", "--chat", "@technostik"])
    assert result.exit_code == 0, result.output

    import yaml

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["telegram"]["targets"]["technostik"]["chat_id"] == -100111


def test_targets_cli_add_requires_exactly_one_reference(tmp_path, monkeypatch):
    group, _ = _isolated_group(tmp_path, monkeypatch, _FakeTelegram())
    runner = CliRunner()
    assert runner.invoke(group, ["add", "x"]).exit_code != 0
    both = runner.invoke(group, ["add", "x", "--chat-id", "1", "--username", "@x"])
    assert both.exit_code != 0


def test_targets_cli_add_profile_writes_selected_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("FASTMARKET_PROFILE", raising=False)
    group = targets_reg.register({}).click_command

    result = CliRunner().invoke(
        group, ["add", "x", "--chat-id", "42", "--profile", "foo"]
    )
    assert result.exit_code == 0, result.output

    import yaml

    path = tmp_path / "fast-market" / "profiles" / "foo" / "message" / "config.yaml"
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["telegram"]["targets"]["x"]["chat_id"] == 42
    # The global active-profile pointer must not be touched.
    assert not (tmp_path / "fast-market" / "active_profile").exists()


def test_profile_scope_restores_env(monkeypatch):
    import os

    monkeypatch.delenv("FASTMARKET_PROFILE", raising=False)
    with targets_reg._profile_scope("foo"):
        assert os.environ["FASTMARKET_PROFILE"] == "foo"
    assert "FASTMARKET_PROFILE" not in os.environ


def test_profile_scope_rejects_invalid_name():
    import click

    with pytest.raises(click.BadParameter):
        with targets_reg._profile_scope("Bad Name"):
            pass
