from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.models import ItemMetadata


@dataclass
class PluginManifest:
    name: str
    source_plugin_class: type
    cli_options: dict[str, list] = field(default_factory=dict)


class SourcePlugin(ABC):
    name: str

    def __init__(self, config: dict, source_config: dict):
        self.config = config
        self.source_config = source_config

    @abstractmethod
    async def fetch_new_items(
        self,
        last_item_id: str | None = None,
        limit: int = 50,
        last_fetched_at: datetime | None = None,
    ) -> list[ItemMetadata]:
        pass

    @abstractmethod
    def validate_identifier(self, identifier: str) -> bool:
        pass

    @abstractmethod
    def get_identifier_display(self, identifier: str) -> str:
        pass
