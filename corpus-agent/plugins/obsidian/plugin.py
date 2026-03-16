from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import structlog
import yaml

from core.models import Document
from plugins.base import ItemMeta, SourcePlugin

logger = structlog.get_logger(__name__)


class ObsidianPlugin(SourcePlugin):
    name = "obsidian"

    def __init__(self, config: dict[str, object]) -> None:
        try:
            vault_path = config["obsidian"]["vault_path"]  # type: ignore[index]
        except Exception as exc:
            raise ValueError("Missing obsidian.vault_path in config") from exc
        self.vault = Path(str(vault_path))
        if not self.vault.exists():
            raise FileNotFoundError(f"Obsidian vault not found: {self.vault}")

    def list_items(self, limit: int, since: datetime | None = None) -> list[ItemMeta]:
        metas: list[ItemMeta] = []
        files = sorted(self.vault.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        for file in files:
            updated = datetime.fromtimestamp(file.stat().st_mtime)
            if since and updated <= since:
                continue
            metas.append(ItemMeta(source_id=file.name, updated_at=updated))
            if len(metas) >= limit:
                break
        return metas

    def _parse(self, raw: str) -> tuple[dict[str, object], str]:
        if raw.startswith("---\n"):
            end = raw.find("\n---\n", 4)
            if end > -1:
                meta = yaml.safe_load(raw[4:end]) or {}
                return meta, raw[end + 5 :]
        return {}, raw

    def fetch(self, item_meta: ItemMeta) -> Document:
        path = self.vault / item_meta.source_id
        raw = path.read_text(encoding="utf-8")
        metadata, body = self._parse(raw)
        tags = set(metadata.get("tags", [])) if isinstance(metadata.get("tags"), list) else set()
        tags.update(re.findall(r"(?<!\w)#([\w-]+)", body))
        links = re.findall(r"\[\[([^\]]+)\]\]", body)
        plain = re.sub(r"\[\[([^\]]+)\]\]", r"\1", body)
        return Document(
            source_plugin=self.name,
            source_id=item_meta.source_id,
            title=path.stem,
            raw_text=plain,
            updated_at=item_meta.updated_at,
            metadata=metadata,
            tags=sorted(tags),
            links=links,
        )
