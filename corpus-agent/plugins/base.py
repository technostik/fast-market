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
    def list_items(
        self,
        limit: int,
        since: datetime | None = None,
        known_ids: set[str] | None = None,
    ) -> list[ItemMeta]:
        """Return up to `limit` items to index.

        Args:
            limit:     Maximum number of items to return.
            since:     Date-based cursor (used by file plugins like Obsidian).
                       Skip items whose content date is <= this value.
            known_ids: ID-based cursor (used by API plugins like YouTube).
                       Skip items whose source_id is already in this set.
                       Both cursors are passed; plugins use whichever is appropriate.
        """
        raise NotImplementedError

    @abstractmethod
    def fetch(self, item_meta: ItemMeta) -> Document:
        raise NotImplementedError
