from __future__ import annotations

import logging


class _Logger:
    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)

    def info(self, event: str, **kwargs) -> None:
        self._logger.info("%s %s", event, kwargs)

    def error(self, event: str, **kwargs) -> None:
        self._logger.error("%s %s", event, kwargs)

    def warning(self, event: str, **kwargs) -> None:
        self._logger.warning("%s %s", event, kwargs)


def get_logger(name: str) -> _Logger:
    return _Logger(name)
