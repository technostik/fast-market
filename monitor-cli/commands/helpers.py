from __future__ import annotations

import sys
from dataclasses import asdict

from common.cli.helpers import out

from core.storage import MonitorStorage
from core.scheduler import get_monitor_db_path

_NOISY_LOGGERS = [
    "urllib3",
    "httpx",
    "aiohttp",
    "xmlrpc",
]


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


def _configure_logging(verbose: bool) -> None:
    import logging

    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)-8s] %(name)s %(message)s",
        force=True,
    )
    logging.root.setLevel(level)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(level)

    try:
        from common import structlog as _structlog

        _structlog.configure(
            wrapper_class=_structlog.make_filtering_bound_logger(level),
            logger_factory=_structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    except Exception:
        pass
