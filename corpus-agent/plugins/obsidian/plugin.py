from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import structlog
import yaml

from core.models import Document
from plugins.base import ItemMeta, SourcePlugin

logger = structlog.get_logger(__name__)

# How many files to scan before applying `since` and truncating to `limit`.
# Prevents `limit` being consumed entirely by already-indexed files.
_OBSIDIAN_OVERFETCH_FACTOR = 4
_OBSIDIAN_MAX_SCAN = 2000


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

    def list_items(self, limit: int, since: datetime | None = None, known_ids: set[str] | None = None) -> list[ItemMeta]:
        # Scan more files than requested so `since` filtering doesn't starve `limit`.
        scan_cap = min(limit * _OBSIDIAN_OVERFETCH_FACTOR, _OBSIDIAN_MAX_SCAN)
        files = sorted(self.vault.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

        metas: list[ItemMeta] = []
        for file in files[:scan_cap]:
            updated = datetime.fromtimestamp(file.stat().st_mtime)
            if since and updated <= since:
                # Files are newest-first; once we pass `since` all remaining are older.
                break
            size_chars = file.stat().st_size
            metas.append(ItemMeta(source_id=file.name, updated_at=updated, metadata={"size_bytes": size_chars}))
            if len(metas) >= limit:
                break
        return metas

    def _parse(self, raw: str) -> tuple[dict[str, object], str]:
        if raw.startswith("---\n"):
            end = raw.find("\n---\n", 4)
            if end > -1:
                meta = yaml.safe_load(raw[4:end]) or {}
                return meta, raw[end + 5:]
        return {}, raw

    def fetch(self, item_meta: ItemMeta) -> Document:
        path = self.vault / item_meta.source_id
        raw = path.read_text(encoding="utf-8")
        metadata, body = self._parse(raw)
        tags = set(metadata.get("tags", [])) if isinstance(metadata.get("tags"), list) else set()
        tags.update(re.findall(r"(?<!\w)#([\w-]+)", body))
        links = re.findall(r"\[\[([^\]]+)\]\]", body)
        plain = re.sub(r"\[\[([^\]]+)\]\]", r"\1", body)

        size_bytes = (item_meta.metadata or {}).get("size_bytes", 0)
        logger.info("indexed_note", title=path.stem, size_bytes=size_bytes, tags=len(tags))

        # vault_path stored so the frontend can build obsidian:// URLs
        metadata["vault_path"] = str(self.vault)
        metadata["size_bytes"] = size_bytes

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
