from __future__ import annotations

import re
from datetime import datetime

from common import structlog

from core.embedder import Embedder
from core.handle import make_handle
from core.models import (
    Chunk,
    Document,
    ReindexResult,
    SyncFailure,
    SyncResult,
    SyncResult,
)
from core.sync_errors import SyncError
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
        self._last_error: str | None = None

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

    def sync(
        self,
        plugin: SourcePlugin,
        mode: str,
        limit: int,
        vault_path: str | None = None,
        use_api: bool = False,
        non_public: bool = False,
    ) -> SyncResult:
        known_id_dates = (
            self.store.get_indexed_id_dates(plugin.name) if mode == "new" else {}
        )

        permanent_failures = self.store.get_permanent_failures(plugin.name)

        list_kwargs = {"limit": limit, "known_id_dates": known_id_dates}
        if hasattr(plugin, "list_items"):
            import inspect

            sig = inspect.signature(plugin.list_items)
            if "use_api" in sig.parameters:
                list_kwargs["use_api"] = use_api
            if "non_public" in sig.parameters:
                list_kwargs["non_public"] = non_public

        items = plugin.list_items(**list_kwargs)

        logger.info(
            "sync_started",
            source=plugin.name,
            mode=mode,
            limit=limit,
            use_api=use_api,
            non_public=non_public,
            known_ids=len(known_id_dates),
            permanent_failures=len(permanent_failures),
            items_available=len(items),
        )

        processed = indexed = skipped = 0
        failures: list[SyncFailure] = []
        warning: str | None = None

        for item in items:
            if item.source_id in permanent_failures:
                logger.info(
                    "skipping_permanent_failure",
                    source=plugin.name,
                    source_id=item.source_id,
                )
                skipped += 1
                continue

            processed += 1
            try:
                document = plugin.fetch(item)
                document.handle = make_handle(
                    document.source_plugin, document.source_id, document.title
                )
                content_hash = self.embedder.hash_text(document.raw_text)
                changed = self.store.upsert_document(document, content_hash)

                if not changed:
                    skipped += 1
                    _log_item(plugin.name, document, "skipped")
                    continue

                chunks = self._build_chunks(document)
                self.store.replace_chunks(
                    document.source_plugin, document.source_id, chunks
                )
                self.store.clear_failure(plugin.name, item.source_id)
                indexed += 1
                _log_item(plugin.name, document, "indexed", chunks=len(chunks))

            except SyncError as exc:
                error_type = "permanent" if exc.permanent else "transient"
                self._last_error = str(exc)
                self.store.record_failure(
                    plugin.name, item.source_id, str(exc), error_type, vault_path
                )
                logger.error(
                    "sync_item_failed",
                    source=plugin.name,
                    source_id=item.source_id,
                    error_type=error_type,
                    error=str(exc),
                )
                failures.append(SyncFailure(source_id=item.source_id, error=str(exc)))
            except Exception as exc:
                self._last_error = str(exc)
                self.store.record_failure(
                    plugin.name, item.source_id, str(exc), "transient", vault_path
                )
                logger.error(
                    "sync_item_failed",
                    source=plugin.name,
                    source_id=item.source_id,
                    error_type="transient",
                    error=str(exc),
                )
                failures.append(SyncFailure(source_id=item.source_id, error=str(exc)))

        if processed == 0 and len(items) == 0:
            last_error = self._last_error
            if last_error and "quota" in str(last_error).lower():
                logger.error(
                    "sync_quota_error",
                    source=plugin.name,
                    message=f"YouTube API quota exceeded: {last_error}",
                )
                raise RuntimeError(
                    f"YouTube API quota exceeded. {last_error}. Try again later or use --non-public (RSS mode)."
                )
            if last_error:
                logger.warning(
                    "sync_no_items_with_error",
                    source=plugin.name,
                    warning=f"No items found for {plugin.name}. Error: {last_error}",
                    last_error=last_error,
                )
                warning = f"No items found for {plugin.name}. Check API credentials, RSS feed, or network connection."
            else:
                warning = f"No items found for {plugin.name}. Check API credentials, RSS feed, or network connection."
            logger.warning("sync_no_items", source=plugin.name, warning=warning)
        elif processed == 0 and len(items) > 0:
            warning = f"All {len(items)} items skipped (all permanent failures or already indexed)."
            logger.warning(
                "sync_all_skipped",
                source=plugin.name,
                warning=warning,
                skipped=len(items),
            )

        return SyncResult(
            plugin.name, processed, indexed, skipped, failures, warning=warning
        )

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
    fields: dict = {
        "source": source,
        "handle": document.handle,
        "title": document.title,
        "status": status,
    }
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
