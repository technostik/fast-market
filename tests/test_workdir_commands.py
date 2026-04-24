"""Tests for toolsetup backup command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from commands.backup.register import register
from commands.snapshot_service import (
    SOURCE_CONFIG,
    SOURCE_WORKDIR,
    SOURCE_DATA,
    _is_snapped,
    get_snapshot_root,
)


@pytest.fixture()
def tmp_workdir(tmp_path: Path) -> Path:
    """Create a temporary workdir with some files."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "file1.txt").write_text("content1", encoding="utf-8")
    (workdir / "file2.txt").write_text("content2", encoding="utf-8")
    (workdir / "file3.md").write_text("# Hello", encoding="utf-8")
    return workdir


@pytest.fixture()
def tmp_config_dir(tmp_path: Path) -> Path:
    """Create a temporary config directory."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "config1.yaml").write_text("key: value1", encoding="utf-8")
    (config / "config2.yaml").write_text("key: value2", encoding="utf-8")
    return config


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "data1.json").write_text('{"a": 1}', encoding="utf-8")
    (data / "data2.json").write_text('{"b": 2}', encoding="utf-8")
    return data


@pytest.fixture()
def mock_snapshot_root(tmp_path: Path, monkeypatch):
    """Mock the snapshot root to use a temp path."""
    import commands.snapshot_service as mod

    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    monkeypatch.setattr(mod, "DEFAULT_SNAPSHOT_ROOT", snapshot_root)
    return snapshot_root


@pytest.fixture()
def mock_workdir_config(tmp_workdir: Path):
    """Mock the config to return the test workdir."""
    with patch("commands.snapshot_service.load_common_config") as mock_cfg:
        mock_cfg.return_value = {"workdir_root": str(tmp_workdir)}
        yield mock_cfg


@pytest.fixture()
def mock_config_source(tmp_config_dir: Path, monkeypatch):
    """Mock the config source directory."""
    import commands.snapshot_service as mod

    monkeypatch.setattr(mod, "_get_config_source", lambda: tmp_config_dir)
    return tmp_config_dir


@pytest.fixture()
def mock_data_source(tmp_data_dir: Path, monkeypatch):
    """Mock the data source directory."""
    import commands.snapshot_service as mod
    import commands.backup.register as reg_mod

    monkeypatch.setattr(mod, "_get_data_source", lambda: tmp_data_dir)
    monkeypatch.setattr(reg_mod, "_get_data_source", lambda: tmp_data_dir)
    return tmp_data_dir


@pytest.fixture()
def mock_workdir_source(tmp_workdir: Path, monkeypatch):
    """Mock the workdir source directory."""
    import commands.snapshot_service as mod

    monkeypatch.setattr(mod, "_get_workdir_source", lambda: tmp_workdir)
    return tmp_workdir


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def backup_cmd():
    return register()


class TestBackupSnapshot:
    def test_snapshot_workdir(
        self, backup_cmd, mock_snapshot_root, mock_workdir_config, runner
    ):
        result = runner.invoke(backup_cmd, ["snapshot", "--source-type", "workdir"])
        assert result.exit_code == 0
        assert "snapped" in result.output.lower()

        # Verify state is updated
        snapshot_root = get_snapshot_root()
        assert _is_snapped(snapshot_root, SOURCE_WORKDIR) is True

    def test_snapshot_config(
        self, backup_cmd, mock_snapshot_root, mock_config_source, runner
    ):
        result = runner.invoke(backup_cmd, ["snapshot", "--source-type", "config"])
        assert result.exit_code == 0
        assert "snapped" in result.output.lower()

        snapshot_root = get_snapshot_root()
        assert _is_snapped(snapshot_root, SOURCE_CONFIG) is True

    def test_snapshot_data(
        self, backup_cmd, mock_snapshot_root, mock_data_source, runner
    ):
        result = runner.invoke(backup_cmd, ["snapshot", "--source-type", "data"])
        assert result.exit_code == 0
        assert "snapped" in result.output.lower()

        snapshot_root = get_snapshot_root()
        assert _is_snapped(snapshot_root, SOURCE_DATA) is True

    def test_snapshot_all_sources(
        self,
        backup_cmd,
        mock_snapshot_root,
        mock_workdir_config,
        mock_config_source,
        mock_data_source,
        runner,
    ):
        result = runner.invoke(backup_cmd, ["snapshot"])
        assert result.exit_code == 0
        # Should contain multiple "snapped" messages
        assert result.output.count("snapped") == 3

        # Verify all sources are snapped
        snapshot_root = get_snapshot_root()
        assert _is_snapped(snapshot_root, SOURCE_WORKDIR) is True
        assert _is_snapped(snapshot_root, SOURCE_CONFIG) is True
        assert _is_snapped(snapshot_root, SOURCE_DATA) is True


class TestBackupRestore:
    def test_restore_workdir(
        self, backup_cmd, mock_snapshot_root, mock_workdir_config, runner, tmp_workdir
    ):
        # Snapshot first
        runner.invoke(backup_cmd, ["snapshot", "--source-type", "workdir"])

        # Modify files
        (tmp_workdir / "file1.txt").write_text("modified", encoding="utf-8")

        # Restore
        result = runner.invoke(backup_cmd, ["restore", "--source-type", "workdir"])
        assert result.exit_code == 0

        # Verify original content restored
        assert (tmp_workdir / "file1.txt").read_text(encoding="utf-8") == "content1"

    def test_restore_requires_source_type(self, backup_cmd, runner):
        result = runner.invoke(backup_cmd, ["restore"])
        assert result.exit_code != 0


class TestBackupStatus:
    def test_status_workdir_snapped(
        self, backup_cmd, mock_snapshot_root, mock_workdir_config, runner
    ):
        runner.invoke(backup_cmd, ["snapshot", "--source-type", "workdir"])
        result = runner.invoke(backup_cmd, ["status", "--source-type", "workdir"])
        assert result.exit_code == 0
        assert "SNAPPED" in result.output

    def test_status_config_not_snapped(
        self, backup_cmd, mock_snapshot_root, mock_config_source, runner
    ):
        result = runner.invoke(backup_cmd, ["status", "--source-type", "config"])
        assert result.exit_code == 0
        assert "NOT snapped" in result.output or "not snapped" in result.output.lower()

    def test_status_requires_source_type(self, backup_cmd, runner):
        result = runner.invoke(backup_cmd, ["status"])
        assert result.exit_code != 0


class TestBackupList:
    def test_list_workdir_snapshots(
        self, backup_cmd, mock_snapshot_root, mock_workdir_config, runner
    ):
        runner.invoke(backup_cmd, ["snapshot", "--source-type", "workdir"])
        result = runner.invoke(backup_cmd, ["list", "--source-type", "workdir"])
        assert result.exit_code == 0
        assert "workdir-" in result.output

    def test_list_config_snapshots(
        self, backup_cmd, mock_snapshot_root, mock_config_source, runner
    ):
        runner.invoke(backup_cmd, ["snapshot", "--source-type", "config"])
        result = runner.invoke(backup_cmd, ["list", "--source-type", "config"])
        assert result.exit_code == 0

    def test_list_empty_when_no_snapshots(
        self, backup_cmd, mock_snapshot_root, mock_workdir_config, runner
    ):
        result = runner.invoke(backup_cmd, ["list", "--source-type", "workdir"])
        assert result.exit_code == 0
        assert "No snapshots found" in result.output

    def test_list_requires_source_type(self, backup_cmd, runner):
        result = runner.invoke(backup_cmd, ["list"])
        assert result.exit_code != 0


class TestBackupRollback:
    def test_rollback_workdir(
        self, backup_cmd, mock_snapshot_root, mock_workdir_config, runner, tmp_workdir
    ):
        # Snapshot
        runner.invoke(backup_cmd, ["snapshot", "--source-type", "workdir"])

        # Modify files
        (tmp_workdir / "file1.txt").write_text("modified", encoding="utf-8")

        # Rollback
        result = runner.invoke(backup_cmd, ["rollback", "--source-type", "workdir"])
        assert result.exit_code == 0
        assert "Rolled back" in result.output

    def test_rollback_requires_source_type(self, backup_cmd, runner):
        result = runner.invoke(backup_cmd, ["rollback"])
        assert result.exit_code != 0


class TestBackupDefault:
    def test_default_shows_help(self, backup_cmd, runner):
        result = runner.invoke(backup_cmd)
        assert result.exit_code == 0
        assert "Usage" in result.output or "Commands" in result.output
