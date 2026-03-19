from __future__ import annotations

from common.cli.helpers import out

from core.storage import MonitorStorage
from core.scheduler import get_monitor_db_path


def get_storage() -> MonitorStorage:
    """Get the monitor storage instance."""
    return MonitorStorage(get_monitor_db_path())


def out_formatted(data: object, fmt: str) -> None:
    """Format output using common helpers."""
    out(data, fmt)
