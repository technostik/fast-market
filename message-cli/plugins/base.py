from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginManifest:
    name: str
    source_plugin_class: type | None = None
    cli_options: dict[str, list] = field(default_factory=dict)
    api_router: Any | None = None
    frontend_js: str | None = None


class MessagePlugin(ABC):
    name: str

    @abstractmethod
    def send_message(self, text: str, parse_mode: str = "Markdown") -> int:
        raise NotImplementedError

    @abstractmethod
    def wait_for_reply(self, timeout: int) -> str:
        raise NotImplementedError

    @abstractmethod
    def wait_for_any_update(self, timeout: int) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def send_alert(
        self, text: str, wait_for_ack: bool = False, timeout: int = 300
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def test_connection(self) -> bool:
        raise NotImplementedError
