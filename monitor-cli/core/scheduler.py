from __future__ import annotations

from pathlib import Path

from common.core.paths import get_tool_data_dir


def get_monitor_data_dir() -> Path:
    """Return the data directory for monitor."""
    return get_tool_data_dir("monitor")


def get_monitor_db_path() -> Path:
    """Return the database path for monitor."""
    return get_monitor_data_dir() / "monitor.db"
