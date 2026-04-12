"""Tests for toolsetup workdir snapshot commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from commands.workdir.register import (
    _do_snapshot,
    _do_restore,
    _do_rollback,
    _get_workdir_root,
    _is_snapped,
    _list_snapshots,
    _load_state,
    _save_state,
    _show_status,
    register,
)


@pytest.fixture()
def tmp_workdir(tmp_path: Path) -> Path:
    """Create a temporary workdir with some files."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    # Create some flat files (no subdirs)
    (workdir / "file1.txt").write_text("content1", encoding="utf-8")
    (workdir / "file2.txt").write_text("content2", encoding="utf-8")
    (workdir / "file3.md").write_text("# Hello", encoding="utf-8")
    # Create a subdirectory (should be ignored)
    subdir = workdir / "subdir"
    subdir.mkdir()
    (subdir / "nested.txt").write_text("nested", encoding="utf-8")
    return workdir


@pytest.fixture()
def tmp_snapshot_dir(tmp_path: Path) -> Path:
    """Create a temporary snapshot directory."""
    snap_dir = tmp_path / "workdir-snapshots"
    snap_dir.mkdir()
    return snap_dir


@pytest.fixture()
def mock_config(tmp_workdir: Path):
    """Mock the config to return the test workdir."""
    with patch("commands.workdir.register.load_common_config") as mock_cfg:
        mock_cfg.return_value = {"workdir": str(tmp_workdir)}
        yield mock_cfg


@pytest.fixture()
def mock_paths(tmp_snapshot_dir: Path, monkeypatch):
    """Mock the snapshot data dir to use a temp path."""
    import commands.workdir.register as mod
    monkeypatch.setattr(mod, "WORKDIR_SNAPSHOT_DATA_DIR", tmp_snapshot_dir)
    yield tmp_snapshot_dir


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def workdir_cmd():
    return register()


class TestGetWorkdirRoot:
    def test_returns_workdir_from_config(self, mock_config, tmp_workdir):
        result = _get_workdir_root()
        assert result == tmp_workdir

    def test_returns_none_on_error(self):
        with patch("commands.workdir.register.load_common_config", side_effect=Exception("fail")):
            result = _get_workdir_root()
            assert result is None


class TestSnapshot:
    def test_snapshot_copies_flat_files_only(self, tmp_workdir, mock_config, mock_paths):
        _do_snapshot()

        state = _load_state()
        assert state["snapped"] is True
        assert state["sentinel"] is not None

        sentinel_dir = mock_paths / state["sentinel"]
        assert sentinel_dir.exists()

        # Check only flat files were copied (no subdirs)
        files = list(sentinel_dir.iterdir())
        assert len(files) == 3
        file_names = {f.name for f in files}
        assert file_names == {"file1.txt", "file2.txt", "file3.md"}

        # Verify content matches
        assert (sentinel_dir / "file1.txt").read_text(encoding="utf-8") == "content1"

    def test_snapshot_fails_if_not_snapped_twice(self, tmp_workdir, mock_config, mock_paths, capsys):
        _do_snapshot()
        _do_snapshot()  # Second snap should fail

        captured = capsys.readouterr()
        assert "already snapped" in captured.out

    def test_snapshot_fails_if_workdir_not_configured(self, mock_paths, capsys):
        with patch("commands.workdir.register.load_common_config", return_value={}):
            _do_snapshot()

        captured = capsys.readouterr()
        assert "workdir not configured" in captured.out

    def test_snapshot_fails_if_workdir_not_exists(self, mock_paths, capsys):
        with patch("commands.workdir.register.load_common_config", return_value={"workdir": "/nonexistent/path"}):
            _do_snapshot()

        captured = capsys.readouterr()
        assert "workdir does not exist" in captured.out


class TestRestore:
    def test_restore_copies_files_back(self, tmp_workdir, mock_config, mock_paths):
        # Snapshot first
        _do_snapshot()

        # Modify the workdir files
        (tmp_workdir / "file1.txt").write_text("modified", encoding="utf-8")

        # Restore
        _do_restore()

        # Check original content is restored
        assert (tmp_workdir / "file1.txt").read_text(encoding="utf-8") == "content1"
        assert (tmp_workdir / "file2.txt").read_text(encoding="utf-8") == "content2"

        # State should be reset
        assert _is_snapped() is False

    def test_restore_backs_up_existing_files(self, tmp_workdir, mock_config, mock_paths):
        _do_snapshot()

        # Create a new file in workdir that wasn't in snapshot
        (tmp_workdir / "new_file.txt").write_text("new content", encoding="utf-8")

        _do_restore()

        # Only files that were in snapshot should be restored, new file backed up
        assert (tmp_workdir / "file1.txt").read_text(encoding="utf-8") == "content1"

    def test_restore_fails_if_not_snapped(self, mock_paths, capsys):
        _do_restore()

        captured = capsys.readouterr()
        assert "not snapped" in captured.out

    def test_restore_fails_if_snapshot_dir_missing(self, tmp_workdir, mock_config, mock_paths):
        # Manually set state to snapped but don't create snapshot
        _save_state({"snapped": True, "sentinel": "nonexistent-sentinel"})

        _do_restore()

        # State should be cleaned up
        state = _load_state()
        assert state["snapped"] is False


class TestStatus:
    def test_status_shows_snapped(self, tmp_workdir, mock_config, mock_paths, capsys):
        _do_snapshot()

        _show_status()
        captured = capsys.readouterr()
        assert "SNAPPED" in captured.out

    def test_status_shows_not_snapped(self, tmp_workdir, mock_config, mock_paths, capsys):
        _show_status()
        captured = capsys.readouterr()
        assert "NOT snapped" in captured.out


class TestList:
    def test_list_shows_snapshots(self, tmp_workdir, mock_config, mock_paths, capsys):
        _do_snapshot()

        _list_snapshots()
        captured = capsys.readouterr()
        assert "workdir-" in captured.out
        assert "file(s)" in captured.out

    def test_list_empty_when_no_snapshots(self, mock_paths, capsys):
        _list_snapshots()
        captured = capsys.readouterr()
        assert "No snapshots found" in captured.out


class TestRollback:
    def test_rollback_restores_then_resnaps(self, tmp_workdir, mock_config, mock_paths, capsys):
        _do_snapshot()

        # Modify files
        (tmp_workdir / "file1.txt").write_text("modified", encoding="utf-8")

        _do_rollback()
        captured = capsys.readouterr()
        assert "Rolled back" in captured.out

        # Should be snapped again
        assert _is_snapped() is True


class TestCLICommands:
    def test_cli_snapshot(self, workdir_cmd, tmp_workdir, mock_config, mock_paths, runner):
        result = runner.invoke(workdir_cmd, ["snapshot"])
        assert result.exit_code == 0
        assert "Snapped" in result.output or "snapped" in result.output

    def test_cli_restore(self, workdir_cmd, tmp_workdir, mock_config, mock_paths, runner):
        # First snapshot
        _do_snapshot()

        result = runner.invoke(workdir_cmd, ["restore"])
        assert result.exit_code == 0

    def test_cli_status(self, workdir_cmd, tmp_workdir, mock_config, mock_paths, runner):
        result = runner.invoke(workdir_cmd, ["status"])
        assert result.exit_code == 0

    def test_cli_list(self, workdir_cmd, tmp_workdir, mock_config, mock_paths, runner):
        _do_snapshot()
        result = runner.invoke(workdir_cmd, ["list"])
        assert result.exit_code == 0

    def test_cli_default_shows_status(self, workdir_cmd, tmp_workdir, mock_config, mock_paths, runner):
        result = runner.invoke(workdir_cmd)
        assert result.exit_code == 0
        # Should show status
        assert "snapped" in result.output.lower() or "SNAPPED" in result.output
