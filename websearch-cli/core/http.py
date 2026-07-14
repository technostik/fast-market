from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx


class Transport(ABC):
    """Fetches a URL and returns the response body as text.

    Abstracted so tests can inject a fake that returns canned responses
    without touching the network.
    """

    @abstractmethod
    def get(
        self, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> str:
        raise NotImplementedError


class HttpTransport(Transport):
    """Real HTTP transport backed by httpx."""

    def get(
        self, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> str:
        response = httpx.get(url, params=params, headers=headers or {}, timeout=20.0, follow_redirects=True)
        response.raise_for_status()
        return response.text
