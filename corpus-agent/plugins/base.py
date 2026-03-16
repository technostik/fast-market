from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from core.models import Document


@dataclass(slots=True)
class ItemMeta:
    source_id: str
    updated_at: datetime | None = None
    metadata: dict[str, object] | None = None


class SourcePlugin(ABC):
    name: str

    @abstractmethod
    def list_items(self, limit: int, since: datetime | None = None) -> list[ItemMeta]:
        raise NotImplementedError

    @abstractmethod
    def fetch(self, item_meta: ItemMeta) -> Document:
        raise NotImplementedError
