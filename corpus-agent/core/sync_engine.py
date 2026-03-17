from __future__ import annotations

import re
from datetime import datetime

import structlog

from core.embedder import Embedder
from core.handle import make_handle
from core.models import Chunk, Document, ReindexResult, SyncFailure, SyncResult
from plugins.base import SourcePlugin
from storage.sqlite_store import SQLiteStore

logger = structlog.get_logger(__name__)


def chunk_by_sections(document: Document) -> list[str]:
    parts = re.split(r"\n(?=# )|\n(?=## )", document.raw_text)
    chunks: list[str] = []
    for part in parts:
        content = part.strip()
        if content:
            chunks.append(content)
    return chunks or [document.raw_text]


class SyncEngine:
    def __init__(self, store: SQLiteStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    def _build_chunks(self, document: Document) -> list[Chunk]:
        texts = chunk_by_sections(document)
        embedded = self.embedder.embed_texts(texts)
        chunks: list[Chunk] = []
        for ix, (content_hash, vector) in enumerate(embedded):
            chunks.append(
                Chunk(
                    source_plugin=document.source_plugin,
                    source_id=document.source_id,
                    chunk_index=ix,
                    content=texts[ix],
                    content_hash=content_hash,
                    embedding=vector,
                )
            )
        return chunks

    def sync(self, plugin: SourcePlugin, mode: str, limit: int) -> SyncResult:
        # Two cursor strategies depending on plugin:
        #
        # ID-based (YouTube): pass known_ids so the plugin skips already-indexed
        # videos while walking the playlist newest-first. A date cursor fails here
        # because published_at of every past video is older than the newest indexed
        # one — so after the first sync, all remaining videos are silently skipped.
        #
        # Date-based (Obsidian): pass since = MAX(updated_at) so the plugin skips
        # files whose mtime hasn't advanced past the last indexed timestamp.
        #
        # Plugins may use either or both; unused kwargs are ignored.
        if mode == "new":
            known_ids = self.store.get_indexed_ids(plugin.name)
            since = self.store.get_latest_content_date(plugin.name)
        else:  # backfill — ignore all cursors
            known_ids = set()
            since = None

        items = plugin.list_items(limit=limit, since=since, known_ids=known_ids)
        processed = indexed = skipped = 0
        failures: list[SyncFailure] = []

        for item in items:
            processed += 1
            try:
                document = plugin.fetch(item)
                document.handle = make_handle(document.source_plugin, document.source_id, document.title)
                content_hash = self.embedder.hash_text(document.raw_text)
                changed = self.store.upsert_document(document, content_hash)

                if not changed:
                    skipped += 1
                    _log_item(plugin.name, document, "skipped")
                    continue

                chunks = self._build_chunks(document)
                self.store.replace_chunks(document.source_plugin, document.source_id, chunks)
                indexed += 1
                _log_item(plugin.name, document, "indexed", chunks=len(chunks))

            except Exception as exc:
                logger.error("sync_item_failed", source=plugin.name, source_id=item.source_id, error=str(exc))
                failures.append(SyncFailure(source_id=item.source_id, error=str(exc)))

        return SyncResult(plugin.name, processed, indexed, skipped, failures)

    def reindex(self, plugin: SourcePlugin) -> ReindexResult:
        rows = self.store.get_documents_raw(plugin.name)
        self.store.delete_source_chunks(plugin.name)
        chunk_count = 0
        for row in rows:
            doc = Document(
                source_plugin=row["source_plugin"],
                source_id=row["source_id"],
                title=row["title"],
                raw_text=row["raw_text"],
                updated_at=datetime.utcnow(),
            )
            chunks = self._build_chunks(doc)
            chunk_count += len(chunks)
            self.store.replace_chunks(doc.source_plugin, doc.source_id, chunks)
        return ReindexResult(plugin.name, len(rows), chunk_count)


def _log_item(source: str, document: Document, status: str, **extra) -> None:
    fields: dict = {"source": source, "handle": document.handle, "title": document.title, "status": status}
    if source == "youtube":
        if document.duration_seconds:
            h, rem = divmod(document.duration_seconds, 3600)
            m, s = divmod(rem, 60)
            fields["duration"] = f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"
        if document.privacy_status:
            fields["privacy"] = document.privacy_status
    if source == "obsidian":
        fields["chars"] = len(document.raw_text)
    fields.update(extra)
    logger.info("item_processed", **fields)
