from __future__ import annotations

# Thin structlog shim.
# All loggers share a single StreamHandler on stderr.
# Verbosity is controlled globally via logging.root.setLevel() —
# each log() call checks the root level at call time, so loggers
# created before _configure_logging() are silenced retroactively.

import logging
import sys

_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s"))


class _Logger:
    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)
        self._log.addHandler(_handler)
        # Do NOT set level here — defers to root logger set by _configure_logging()
        self._log.propagate = False

    def _emit(self, level: int, event: str, **kwargs) -> None:
        # Check root level dynamically so loggers created before configure() are affected
        if logging.root.level > level:
            return
        msg = event + (" " + str(kwargs) if kwargs else "")
        self._log.log(level, msg)

    def info(self, event: str, **kwargs) -> None:
        self._emit(logging.INFO, event, **kwargs)

    def error(self, event: str, **kwargs) -> None:
        self._emit(logging.ERROR, event, **kwargs)

    def warning(self, event: str, **kwargs) -> None:
        self._emit(logging.WARNING, event, **kwargs)


def get_logger(name: str) -> _Logger:
    return _Logger(name)
