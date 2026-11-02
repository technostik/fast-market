"""Tests for `toolsetup profile rename`."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from commands.profile.register import register


@pytest.fixture()
def profile_cmd():
    return register()


@pytest.fixture()
def xdg(tmp_path: Path, monkeypatch):
    """Point every XDG root at a temp dir and clear profile env overrides."""
    roots = {
        "config": tmp_path / "config",
        "data": tmp_path / "data",
        "cache": tmp_path / "cache",
    }
    monkeypatch.setenv("XDG_CONFIG_HOME", str(roots["config"]))
    monkeypatch.setenv("XDG_DATA_HOME", str(roots["data"]))
    monkeypatch.setenv("XDG_CACHE_HOME", str(roots["cache"]))
    monkeypatch.delenv("FASTMARKET_PROFILE", raising=False)
    return roots


def _make_profile(xdg: dict[str, Path], name: str) -> Path:
    """Create a profile in all three roots, with a self-referencing config."""
    config = xdg["config"] / "fast-market" / "profiles" / name / "common"
    config.mkdir(parents=True)
    (config / "config.yaml").write_text(
        f"youtube_path: {xdg['config']}/fast-market/profiles/{name}/common/youtube\n"
        f"similar_root: {xdg['config']}/fast-market/myprofiles/{name}\n"
        f"similar_prefix: {xdg['config']}/fast-market/profiles/{name}_extra\n",
        encoding="utf-8",
    )
    (xdg["data"] / "fast-market" / "profiles" / name).mkdir(parents=True)
    (xdg["cache"] / "fast-market" / "profiles" / name).mkdir(parents=True)
    return config


def test_rename_moves_all_roots_and_rewrites_paths(profile_cmd, xdg):
    old_config = _make_profile(xdg, "old")

    result = CliRunner().invoke(profile_cmd, ["rename", "old", "new"])

    assert result.exit_code == 0, result.output
    for kind in ("config", "data", "cache"):
        profile_root = xdg[kind] / "fast-market" / "profiles"
        assert not (profile_root / "old").exists()
        assert (profile_root / "new").is_dir()
    new_config = old_config.parent.parent / "new" / "common" / "config.yaml"
    text = new_config.read_text(encoding="utf-8")
    assert "profiles/new/common/youtube" in text
    assert "profiles/old/" not in text
    # Only the exact profile segment is rewritten, not lookalike paths.
    assert "myprofiles/new" not in text
    assert "fast-market/myprofiles/old" in text
    assert "profiles/old_extra" in text


def test_rename_active_profile_updates_pointer(profile_cmd, xdg):
    _make_profile(xdg, "old")
    runner = CliRunner()
    assert runner.invoke(profile_cmd, ["use", "old"]).exit_code == 0

    result = runner.invoke(profile_cmd, ["rename", "old", "new"])

    assert result.exit_code == 0, result.output
    pointer = xdg["config"] / "fast-market" / "active_profile"
    assert pointer.read_text(encoding="utf-8").strip() == "new"


def test_rename_rejects_existing_destination(profile_cmd, xdg):
    _make_profile(xdg, "old")
    _make_profile(xdg, "new")

    result = CliRunner().invoke(profile_cmd, ["rename", "old", "new"])

    assert result.exit_code != 0
    assert "already exists" in result.output
    assert (xdg["config"] / "fast-market" / "profiles" / "old").is_dir()


def test_rename_rejects_missing_source(profile_cmd, xdg):
    result = CliRunner().invoke(profile_cmd, ["rename", "missing", "new"])
    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_rename_rejects_shared(profile_cmd, xdg):
    _make_profile(xdg, "old")
    result = CliRunner().invoke(profile_cmd, ["rename", "old", "_shared"])
    assert result.exit_code != 0
    assert "reserved" in result.output


def test_rename_rejects_same_name(profile_cmd, xdg):
    _make_profile(xdg, "old")
    result = CliRunner().invoke(profile_cmd, ["rename", "old", "old"])
    assert result.exit_code != 0
    assert "identical" in result.output
