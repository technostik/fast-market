from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from common import structlog
import yaml

from core.models import Document
from plugins.base import ItemMeta, SourcePlugin

logger = structlog.get_logger(__name__)


class ObsidianPlugin(SourcePlugin):
    name = "obsidian"

    def __init__(self, config: dict[str, object]) -> None:
        try:
            ob_cfg = config["obsidian"]  # type: ignore[index]
            vault_path = ob_cfg["vault_path"]  # type: ignore[index]
        except Exception as exc:
            raise ValueError("Missing obsidian.vault_path in config") from exc
        self.vault = Path(str(vault_path)).expanduser()
        if not self.vault.exists():
            raise FileNotFoundError(f"Obsidian vault not found: {self.vault}")

        # Directories to exclude — matched against every path component.
        # Default: common Obsidian system dirs that should not be indexed.
        default_excludes = {".obsidian", ".trash", ".git"}
        configured = ob_cfg.get("exclude_dirs", [])  # type: ignore[union-attr]
        self._exclude_dirs: set[str] = default_excludes | set(configured)
        if self._exclude_dirs:
            logger.info("obsidian_exclude_dirs", dirs=sorted(self._exclude_dirs))

    def _is_excluded(self, path: Path) -> bool:
        """True if any component of the path relative to vault is in exclude_dirs."""
        try:
            rel = path.relative_to(self.vault)
        except ValueError:
            return False
        return any(part in self._exclude_dirs for part in rel.parts)

    def list_items(
        self,
        limit: int,
        known_id_dates: dict[str, datetime | None] | None = None,
    ) -> list[ItemMeta]:
        """Walk all vault .md files (recursively) newest-mtime-first.

        Returns up to `limit` items that are either:
        - new: source_id (vault-relative path) not in known_id_dates, or
        - modified: mtime has advanced past the indexed updated_at.

        Excludes directories listed in obsidian.exclude_dirs (config) plus
        the built-in defaults: .obsidian, .trash, .git.

        source_id is the vault-relative POSIX path (e.g. "notes/ideas/foo.md")
        so files with the same name in different dirs are correctly distinguished.
        """
        known = known_id_dates or {}
        files = sorted(
            (f for f in self.vault.rglob("*.md") if not self._is_excluded(f)),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        out: list[ItemMeta] = []
        for file in files:
            # Use vault-relative POSIX path as stable, collision-free source_id
            source_id = file.relative_to(self.vault).as_posix()
            mtime = datetime.fromtimestamp(file.stat().st_mtime)

            if source_id in known:
                indexed_at = known[source_id]
                # Skip only when mtime has not advanced (content unchanged).
                # Truncate to second precision to absorb filesystem float rounding.
                if indexed_at is not None and mtime.replace(microsecond=0) <= indexed_at.replace(microsecond=0):
                    continue
                # mtime advanced → file was modified since last index, re-index it

            out.append(ItemMeta(
                source_id=source_id,
                updated_at=mtime,
                metadata={"size_bytes": file.stat().st_size},
            ))
            if len(out) >= limit:
                break  # collected `limit` new/modified items — stop

        logger.info("items_listed", source=self.name, count=len(out))
        return out

    def _parse(self, raw: str) -> tuple[dict[str, object], str]:
        if raw.startswith("---\n"):
            end = raw.find("\n---\n", 4)
            if end > -1:
                meta = yaml.safe_load(raw[4:end]) or {}
                return meta, raw[end + 5:]
        return {}, raw

    def fetch(self, item_meta: ItemMeta) -> Document:
        # source_id is a vault-relative POSIX path
        path = self.vault / item_meta.source_id
        raw = path.read_text(encoding="utf-8")
        metadata, body = self._parse(raw)
        tags = set(metadata.get("tags", [])) if isinstance(metadata.get("tags"), list) else set()
        tags.update(re.findall(r"(?<!\w)#([\w-]+)", body))
        links = re.findall(r"\[\[([^\]]+)\]\]", body)
        plain = re.sub(r"\[\[([^\]]+)\]\]", r"\1", body)

        size_bytes = (item_meta.metadata or {}).get("size_bytes", 0)
        logger.info("indexed_note", title=path.stem, source_id=item_meta.source_id, size_bytes=size_bytes, tags=len(tags))

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
