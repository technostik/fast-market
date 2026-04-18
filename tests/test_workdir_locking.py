"""Tests for workdir locking mechanism."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent

import importlib.util as _ilu

# Load toolsetup-cli's workdir module directly by file path to avoid collision
# with browser-cli's 'commands' package that gets cached in sys.modules first.
_workdir_file = REPO_ROOT / "toolsetup-cli" / "commands" / "setup" / "workdir.py"
try:
    _spec = _ilu.spec_from_file_location("_toolsetup_workdir", _workdir_file)
    workdir_module = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(workdir_module)
except Exception:
    workdir_module = None


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_workdir_root(tmp_path):
    """Create a temporary workdir root."""
    root = tmp_path / "workdir_root"
    root.mkdir()
    return root


@pytest.fixture
def setup_workdir_config(tmp_workdir_root, monkeypatch):
    """Set up mock config with workdir_root."""
    from common.core.config import is_workdir_locked

    config_data = {
        "workdir_root": str(tmp_workdir_root),
        "workdir": str(tmp_workdir_root),
        "workdir_prefix": "work-",
        "lock_wait_timeout": 5,
    }

    def mock_load_config():
        return config_data.copy()

    def mock_save_config(cfg):
        config_data.update(cfg)

    def mock_is_locked(path):
        return is_workdir_locked(str(path))

    monkeypatch.setattr(workdir_module, "load_common_config", mock_load_config)
    monkeypatch.setattr(workdir_module, "save_common_config", mock_save_config)
    monkeypatch.setattr(workdir_module, "is_workdir_locked", mock_is_locked)

    return config_data


def get_workdir_cmd():
    """Get the workdir command."""
    return workdir_module.register()


class TestIsWorkdirLocked:
    """Test the is_workdir_locked function."""

    def test_is_locked_returns_true_when_lock_exists(self, tmp_path):
        """Test that is_locked returns True when .lock exists."""
        from common.core.config import is_workdir_locked, add_workdir_lock

        workdir = tmp_path / "work"
        workdir.mkdir()
        add_workdir_lock(str(workdir))

        assert is_workdir_locked(str(workdir)) is True

    def test_is_locked_returns_false_when_no_lock(self, tmp_path):
        """Test that is_locked returns False when .lock doesn't exist."""
        from common.core.config import is_workdir_locked

        workdir = tmp_path / "work"
        workdir.mkdir()

        assert is_workdir_locked(str(workdir)) is False

    def test_is_locked_returns_false_for_nonexistent_path(self):
        """Test that is_locked returns False for non-existent path."""
        from common.core.config import is_workdir_locked

        assert is_workdir_locked("/nonexistent/path") is False

    def test_is_locked_returns_false_for_none_workdir(self):
        """Test that is_locked returns False when workdir_path is None."""
        from common.core.config import is_workdir_locked

        assert is_workdir_locked(None) is False


class TestAddRemoveWorkdirLock:
    """Test add and remove workdir lock functions."""

    def test_add_workdir_lock_creates_lock_file(self, tmp_path):
        """Test that add_workdir_lock creates .lock file."""
        from common.core.config import add_workdir_lock, is_workdir_locked

        workdir = tmp_path / "work"
        workdir.mkdir()

        result = add_workdir_lock(str(workdir))
        assert result is True
        assert is_workdir_locked(str(workdir)) is True
        assert (workdir / ".lock").exists()

    def test_add_workdir_lock_returns_false_if_already_locked(self, tmp_path):
        """Test that add_workdir_lock returns False if already locked."""
        from common.core.config import add_workdir_lock

        workdir = tmp_path / "work"
        workdir.mkdir()
        (workdir / ".lock").touch()

        result = add_workdir_lock(str(workdir))
        assert result is False

    def test_add_workdir_lock_returns_false_for_nonexistent_path(self):
        """Test that add_workdir_lock returns False for non-existent path."""
        from common.core.config import add_workdir_lock

        result = add_workdir_lock("/nonexistent/path")
        assert result is False

    def test_remove_workdir_lock_removes_lock_file(self, tmp_path):
        """Test that remove_workdir_lock removes .lock file."""
        from common.core.config import add_workdir_lock, remove_workdir_lock, is_workdir_locked

        workdir = tmp_path / "work"
        workdir.mkdir()
        add_workdir_lock(str(workdir))

        result = remove_workdir_lock(str(workdir))
        assert result is True
        assert is_workdir_locked(str(workdir)) is False
        assert not (workdir / ".lock").exists()

    def test_remove_workdir_lock_returns_false_if_not_locked(self, tmp_path):
        """Test that remove_workdir_lock returns False if not locked."""
        from common.core.config import remove_workdir_lock

        workdir = tmp_path / "work"
        workdir.mkdir()

        result = remove_workdir_lock(str(workdir))
        assert result is False


class TestWorkdirLockCommand:
    """Test toolsetup workdir lock/unlock commands."""

    def test_lock_command_creates_lock_file(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that lock command creates .lock file."""
        setup_workdir_config["workdir"] = str(tmp_workdir_root)

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["lock"])

        assert result.exit_code == 0
        assert "locked" in result.output.lower()
        assert (tmp_workdir_root / ".lock").exists()

    def test_unlock_command_removes_lock_file(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that unlock command removes .lock file."""
        setup_workdir_config["workdir"] = str(tmp_workdir_root)
        (tmp_workdir_root / ".lock").touch()

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["unlock"])

        assert result.exit_code == 0
        assert "unlocked" in result.output.lower()
        assert not (tmp_workdir_root / ".lock").exists()

    def test_lock_command_fails_when_already_locked(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that lock command fails when already locked."""
        setup_workdir_config["workdir"] = str(tmp_workdir_root)
        (tmp_workdir_root / ".lock").touch()

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["lock"])

        assert result.exit_code == 0
        assert "already locked" in result.output.lower()

    def test_unlock_command_fails_when_not_locked(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that unlock command fails when not locked."""
        setup_workdir_config["workdir"] = str(tmp_workdir_root)

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["unlock"])

        assert result.exit_code == 0
        assert "not locked" in result.output.lower()


class TestWorkdirIsLockedCommand:
    """Test toolsetup workdir islocked command."""

    def test_islocked_returns_locked_when_locked(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test islocked returns LOCKED when .lock exists."""
        setup_workdir_config["workdir"] = str(tmp_workdir_root)
        (tmp_workdir_root / ".lock").touch()

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["islocked"])

        assert result.exit_code == 0
        assert "LOCKED" in result.output

    def test_islocked_returns_not_locked_when_unlocked(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test islocked returns NOT locked when .lock doesn't exist."""
        setup_workdir_config["workdir"] = str(tmp_workdir_root)

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["islocked"])

        assert result.exit_code == 0
        assert "NOT locked" in result.output


class TestWorkdirListCommand:
    """Test toolsetup workdir list command shows locks."""

    def test_list_shows_locked_workdirs(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that list shows [LOCKED] for locked workdirs."""
        work1 = tmp_workdir_root / "work-001"
        work1.mkdir()
        work2 = tmp_workdir_root / "work-002"
        work2.mkdir()

        (work2 / ".lock").touch()

        setup_workdir_config["workdir"] = str(work1)

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["list"])

        assert result.exit_code == 0
        assert "[LOCKED]" in result.output

    def test_list_shows_current_workdir_with_arrows(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that list shows current workdir with >>> <<<."""
        work1 = tmp_workdir_root / "work-001"
        work1.mkdir()
        work2 = tmp_workdir_root / "work-002"
        work2.mkdir()

        setup_workdir_config["workdir"] = str(work1)

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["list"])

        assert result.exit_code == 0
        assert ">>>" in result.output
        assert "<<<" in result.output
        assert "(current)" in result.output


class TestWorkdirNewCommand:
    """Test toolsetup workdir new command with locking."""

    def test_new_creates_workdir_with_lock(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that new creates a workdir with .lock."""
        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["new"])

        assert result.exit_code == 0
        assert "created" in result.output.lower()
        assert "locked" in result.output.lower()

    def test_new_waits_for_unlock_when_locked(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that new waits for unlock when current workdir is locked."""
        setup_workdir_config["workdir"] = str(tmp_workdir_root)
        (tmp_workdir_root / ".lock").touch()

        workdir_cmd = get_workdir_cmd()

        import threading

        def remove_lock_after_delay():
            time.sleep(0.5)
            (tmp_workdir_root / ".lock").unlink()

        thread = threading.Thread(target=remove_lock_after_delay)
        thread.start()

        result = runner.invoke(workdir_cmd, ["new"])
        thread.join()

        assert result.exit_code == 0

    def test_new_fails_with_no_wait_when_locked(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that new --no-wait fails when current workdir is locked."""
        setup_workdir_config["workdir"] = str(tmp_workdir_root)
        (tmp_workdir_root / ".lock").touch()

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["new", "--no-wait"])

        assert "locked" in result.output.lower()
        assert "force" in result.output.lower() or "no-wait" in result.output.lower()

    def test_new_force_creates_when_locked(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that new --force creates even when current is locked."""
        setup_workdir_config["workdir"] = str(tmp_workdir_root)
        (tmp_workdir_root / ".lock").touch()

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["new", "--force"])

        assert result.exit_code == 0
        assert "created" in result.output.lower()


class TestWorkdirPrevLastCommands:
    """Test that prev/last commands respect locking."""

    def test_prev_fails_when_locked(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that prev fails when current workdir is locked."""
        work1 = tmp_workdir_root / "work-001"
        work1.mkdir()
        work2 = tmp_workdir_root / "work-002"
        work2.mkdir()

        setup_workdir_config["workdir"] = str(work1)
        (work1 / ".lock").touch()

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["prev"])

        assert "locked" in result.output.lower()

    def test_last_fails_when_locked(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that last fails when current workdir is locked."""
        work1 = tmp_workdir_root / "work-001"
        work1.mkdir()
        work2 = tmp_workdir_root / "work-002"
        work2.mkdir()

        setup_workdir_config["workdir"] = str(work1)
        (work1 / ".lock").touch()

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["last"])

        assert "locked" in result.output.lower()


class TestWorkdirReleaseCommand:
    """Test toolsetup workdir release command."""

    def test_release_removes_lock_and_switches_to_previous(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that release removes lock and switches to previous workdir."""
        prev = tmp_workdir_root / "work-prev"
        prev.mkdir()
        curr = tmp_workdir_root / "work-curr"
        curr.mkdir()
        (curr / ".lock").touch()

        setup_workdir_config["workdir"] = str(curr)
        setup_workdir_config["previous_workdir"] = str(prev)

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["release"])

        assert result.exit_code == 0
        assert not (curr / ".lock").exists()
        assert "released" in result.output.lower()

    def test_release_with_bypass_creates_new_workdir(self, runner, tmp_workdir_root, setup_workdir_config):
        """Test that release --bypass creates new workdir."""
        curr = tmp_workdir_root / "work-curr"
        curr.mkdir()
        (curr / ".lock").touch()

        setup_workdir_config["workdir"] = str(curr)

        workdir_cmd = get_workdir_cmd()
        result = runner.invoke(workdir_cmd, ["release", "--bypass"])

        assert result.exit_code == 0
        assert "created" in result.output.lower()


class TestGetLockWaitTimeout:
    """Test the get_lock_wait_timeout function."""

    def test_default_timeout_is_600(self):
        """Test that default timeout is 600 seconds (10 minutes)."""
        from common.core.config import get_lock_wait_timeout, load_common_config

        original = load_common_config
        try:
            import common.core.config as config_module
            config_module.load_common_config = lambda: {}
            assert config_module.get_lock_wait_timeout() == 600
        finally:
            config_module.load_common_config = original

    def test_custom_timeout_from_config(self, monkeypatch):
        """Test that custom timeout is read from config."""
        def mock_load():
            return {"lock_wait_timeout": 300}

        monkeypatch.setattr("common.core.config.load_common_config", mock_load)
        from common.core.config import get_lock_wait_timeout

        assert get_lock_wait_timeout() == 300