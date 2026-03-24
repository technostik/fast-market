from __future__ import annotations

from dataclasses import asdict

from common.cli.helpers import out

from core.storage import MonitorStorage
from core.scheduler import get_monitor_db_path


def get_storage() -> MonitorStorage:
    """Get the monitor storage instance."""
    return MonitorStorage(get_monitor_db_path())


def out_formatted(data: object, fmt: str) -> None:
    """Format output using common helpers."""
    out(data, fmt)


def to_dict(obj: object) -> dict:
    """Convert dataclass (with or without slots) to dict."""
    try:
        return obj.__dict__
    except AttributeError:
        return asdict(obj)
