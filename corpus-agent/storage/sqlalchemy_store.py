from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from common import structlog
from sqlalchemy import text, select, delete
from sqlalchemy.orm import Session

from core.models import Chunk, Document, SearchResult
from common.core.paths import get_tool_data_dir
from common.storage.base import (
    create_memory_engine,
    create_session_factory,
    create_sqlite_engine,
    run_alembic_migrations,
    session_scope,
)
from storage.models import ChunkModel, DocumentModel, SyncFailureModel

logger = structlog.get_logger(__name__)

YOUTUBE_SHORT_MAX_SECONDS = 60


class SearchFilters:
    def __init__(
        self,
        source: str | None = None,
        min_duration: int | None = None,
        max_duration: int | None = None,
        video_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
        privacy_status: str | None = None,
    ) -> None:
        self.source = source
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.video_type = video_type
        self.since = since
        self.until = until
        self.min_size = min_size
        self.max_size = max_size
        self.privacy_status = privacy_status

        if video_type == "short":
            self.max_duration = min(self.max_duration or 9999999, YOUTUBE_SHORT_MAX_SECONDS)
        elif video_type == "long":
            self.min_duration = max(self.min_duration or 0, YOUTUBE_SHORT_MAX_SECONDS + 1)


class _CompatCursor:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows
        self._index = 0

    def fetchone(self):
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self):
        if self._index >= len(self._rows):
            return []
        rows = self._rows[self._index :]
        self._index = len(self._rows)
        return rows


class _CompatConnection:
    """Compatibility wrapper for legacy `store.conn.execute(...)` usage."""

    def __init__(self, store: "SQLAlchemyStore") -> None:
        self._store = store

    def execute(self, sql: str, parameters: tuple | None = None) -> _CompatCursor:
        params = parameters or ()
        with self._store.engine.connect() as conn:
            result = conn.exec_driver_sql(sql, params)
            rows = result.fetchall()
        return _CompatCursor(rows)


class SQLAlchemyStore:
    def __init__(self, path: str | None = None) -> None:
        if path is None:
            path = str(get_tool_data_dir("corpus") / "corpus.db")

        self._path = path
        if path == ":memory:":
            self.engine = create_memory_engine()
        else:
            self.engine = create_sqlite_engine("corpus", "corpus.db", db_path=path)

        self.SessionLocal = create_session_factory(self.engine)
        self._run_migrations()
        self.conn = _CompatConnection(self)

    def _run_migrations(self) -> None:
        if self._path == ":memory:":
            from storage.models import Base

            Base.metadata.create_all(self.engine)
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                            source_plugin, source_id, content
                        )
                        """
                    )
                )
            logger.info("db_migration_complete", backend="sqlalchemy", target="memory")
            return

        alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
        expanded = Path(self._path).expanduser()
        run_alembic_migrations(
            "corpus",
            alembic_ini,
            db_url_override=f"sqlite+pysqlite:///{expanded}",
        )
        logger.info("db_migration_complete", backend="sqlalchemy", path=str(expanded))

    def _session(self):
        return session_scope(self.SessionLocal)

    @staticmethod
    def _row_to_doc_dict(row: dict) -> dict:
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        return result

    def upsert_document(self, document: Document, content_hash: str) -> bool:
        with self._session() as session:
            existing = session.execute(
                select(DocumentModel).where(
                    DocumentModel.source_plugin == document.source_plugin,
                    DocumentModel.source_id == document.source_id,
                )
            ).scalar_one_or_none()
            if existing and existing.content_hash == content_hash:
                return False

            payload = {
                "handle": document.handle,
                "source_plugin": document.source_plugin,
                "source_id": document.source_id,
                "title": document.title,
                "raw_text": document.raw_text,
                "url": document.url,
                "updated_at": document.updated_at.isoformat() if document.updated_at else None,
                "duration_seconds": document.duration_seconds,
                "privacy_status": document.privacy_status,
                "content_hash": content_hash,
                "metadata_json": json.dumps(document.metadata),
            }

            if existing:
                for key, value in payload.items():
                    setattr(existing, key, value)
            else:
                session.add(DocumentModel(**payload))
            return True

    def replace_chunks(self, source_plugin: str, source_id: str, chunks: list[Chunk]) -> None:
        with self._session() as session:
            session.execute(delete(ChunkModel).where(
                ChunkModel.source_plugin == source_plugin,
                ChunkModel.source_id == source_id,
            ))
            session.execute(
                text("DELETE FROM chunks_fts WHERE source_plugin = :source_plugin AND source_id = :source_id"),
                {"source_plugin": source_plugin, "source_id": source_id},
            )
            if not chunks:
                return
            rows = []
            fts_rows = []
            for chunk in chunks:
                rows.append(
                    ChunkModel(
                        source_plugin=chunk.source_plugin,
                        source_id=chunk.source_id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                        embedding_json=json.dumps(chunk.embedding),
                        metadata_json=json.dumps(chunk.metadata),
                    )
                )
                fts_rows.append(
                    {
                        "source_plugin": chunk.source_plugin,
                        "source_id": chunk.source_id,
                        "content": chunk.content,
                    }
                )
            session.add_all(rows)
            session.execute(
                text(
                    "INSERT INTO chunks_fts(source_plugin, source_id, content) "
                    "VALUES(:source_plugin, :source_id, :content)"
                ),
                fts_rows,
            )

    def get_document(self, source_plugin: str, source_id: str) -> dict | None:
        with self._session() as session:
            row = session.execute(
                text(
                    "SELECT handle, source_plugin, source_id, title, raw_text, url, updated_at, "
                    "duration_seconds, privacy_status, metadata_json "
                    "FROM documents WHERE source_plugin=:source_plugin AND source_id=:source_id"
                ),
                {"source_plugin": source_plugin, "source_id": source_id},
            ).mappings().first()
            return self._row_to_doc_dict(row) if row else None

    def get_document_by_handle(self, handle: str) -> dict | None:
        with self._session() as session:
            row = session.execute(
                text(
                    "SELECT handle, source_plugin, source_id, title, raw_text, url, updated_at, "
                    "duration_seconds, privacy_status, metadata_json "
                    "FROM documents WHERE handle=:handle OR source_id=:handle"
                ),
                {"handle": handle},
            ).mappings().first()
            return self._row_to_doc_dict(row) if row else None

    def delete_document(self, source_plugin: str, source_id: str) -> bool:
        with self._session() as session:
            exists = session.execute(
                text("SELECT 1 FROM documents WHERE source_plugin=:source_plugin AND source_id=:source_id"),
                {"source_plugin": source_plugin, "source_id": source_id},
            ).first()
            if not exists:
                return False
            session.execute(
                text("DELETE FROM documents WHERE source_plugin=:source_plugin AND source_id=:source_id"),
                {"source_plugin": source_plugin, "source_id": source_id},
            )
            session.execute(
                text("DELETE FROM chunks WHERE source_plugin=:source_plugin AND source_id=:source_id"),
                {"source_plugin": source_plugin, "source_id": source_id},
            )
            session.execute(
                text("DELETE FROM chunks_fts WHERE source_plugin=:source_plugin AND source_id=:source_id"),
                {"source_plugin": source_plugin, "source_id": source_id},
            )
            logger.info("document_deleted", source_plugin=source_plugin, source_id=source_id)
            return True

    def delete_document_by_handle(self, handle: str) -> bool:
        with self._session() as session:
            row = session.execute(
                text("SELECT source_plugin, source_id FROM documents WHERE handle=:handle OR source_id=:handle"),
                {"handle": handle},
            ).mappings().first()
        if not row:
            return False
        return self.delete_document(row["source_plugin"], row["source_id"])

    def keyword_search(self, query: str, limit: int, filters: SearchFilters | None = None) -> list[SearchResult]:
        with self._session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT d.handle, d.source_plugin, d.source_id, d.title, d.duration_seconds,
                           d.privacy_status, c.content
                    FROM chunks_fts c
                    JOIN documents d ON d.source_plugin=c.source_plugin AND d.source_id=c.source_id
                    WHERE chunks_fts MATCH :query
                    LIMIT :limit
                    """
                ),
                {"query": query, "limit": limit * 5},
            ).mappings().all()
        results = [
            SearchResult(
                source_plugin=row["source_plugin"],
                source_id=row["source_id"],
                handle=row["handle"],
                title=row["title"],
                excerpt=row["content"][:220],
                score=1.0,
                duration_seconds=row["duration_seconds"],
                privacy_status=row["privacy_status"],
            )
            for row in rows
        ]
        return _apply_filters(results, filters)[:limit]

    def semantic_search(self, query_vector: list[float], limit: int, filters: SearchFilters | None = None) -> list[SearchResult]:
        with self._session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT c.source_plugin, c.source_id, c.content, c.embedding_json,
                           d.handle, d.title, d.duration_seconds, d.privacy_status
                    FROM chunks c
                    JOIN documents d ON d.source_plugin=c.source_plugin AND d.source_id=c.source_id
                    """
                )
            ).mappings().all()
        q = [float(value) for value in query_vector]
        scored: list[tuple[float, dict]] = []
        for row in rows:
            emb = [float(value) for value in json.loads(row["embedding_json"])]
            score = sum(a * b for a, b in zip(q, emb))
            scored.append((score, row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        results = [
            SearchResult(
                source_plugin=row["source_plugin"],
                source_id=row["source_id"],
                handle=row["handle"],
                title=row["title"],
                excerpt=row["content"][:220],
                score=score,
                duration_seconds=row["duration_seconds"],
                privacy_status=row["privacy_status"],
            )
            for score, row in scored
        ]
        return _apply_filters(results, filters)[:limit]

    def list_documents(self, source: str | None = None, limit: int = 50, filters: SearchFilters | None = None) -> list[dict]:
        with self._session() as session:
            if source:
                rows = session.execute(
                    text(
                        "SELECT handle, source_plugin, source_id, title, url, updated_at, "
                        "duration_seconds, privacy_status, metadata_json "
                        "FROM documents WHERE source_plugin=:source ORDER BY updated_at DESC LIMIT :limit"
                    ),
                    {"source": source, "limit": limit * 5},
                ).mappings().all()
            else:
                rows = session.execute(
                    text(
                        "SELECT handle, source_plugin, source_id, title, url, updated_at, "
                        "duration_seconds, privacy_status, metadata_json "
                        "FROM documents ORDER BY updated_at DESC LIMIT :limit"
                    ),
                    {"limit": limit * 5},
                ).mappings().all()
        items = [self._row_to_doc_dict(row) for row in rows]
        if filters:
            items = _apply_filters_dicts(items, filters)
        return items[:limit]

    def list_documents_extended(
        self,
        source: str | None = None,
        filters: SearchFilters | None = None,
        order_by: str = "date",
        reverse: bool = False,
        limit: int = 1000,
    ) -> list[dict]:
        query = (
            "SELECT handle, source_plugin, source_id, title, raw_text, url, "
            "updated_at, duration_seconds, privacy_status, metadata_json "
            "FROM documents WHERE 1=1"
        )
        params: dict[str, object] = {"limit": limit}

        if source:
            query += " AND source_plugin=:source"
            params["source"] = source

        if filters:
            if filters.since:
                query += " AND updated_at >= :since"
                params["since"] = f"{filters.since}T00:00:00"
            if filters.until:
                query += " AND updated_at <= :until"
                params["until"] = f"{filters.until}T23:59:59"
            if filters.min_duration is not None:
                query += " AND duration_seconds >= :min_duration"
                params["min_duration"] = filters.min_duration
            if filters.max_duration is not None:
                query += " AND duration_seconds <= :max_duration"
                params["max_duration"] = filters.max_duration
            if filters.privacy_status:
                query += " AND privacy_status = :privacy_status"
                params["privacy_status"] = filters.privacy_status

        order_field_map = {
            "date": "updated_at",
            "size": "LENGTH(raw_text)",
            "duration": "COALESCE(duration_seconds, 0)",
            "title": "title COLLATE NOCASE",
        }
        order_field = order_field_map.get(order_by, "updated_at")
        order_dir = "ASC" if reverse else "DESC"
        query += f" ORDER BY {order_field} {order_dir} LIMIT :limit"

        with self._session() as session:
            rows = session.execute(text(query), params).mappings().all()
        docs = [self._row_to_doc_dict(row) for row in rows]

        if filters and (filters.min_size is not None or filters.max_size is not None):
            filtered = []
            for doc in docs:
                size = len(doc.get("raw_text", "") or "")
                if filters.min_size is not None and size < filters.min_size:
                    continue
                if filters.max_size is not None and size > filters.max_size:
                    continue
                filtered.append(doc)
            docs = filtered

        return docs

    def delete_all(self) -> None:
        with self._session() as session:
            session.execute(text("DELETE FROM documents"))
            session.execute(text("DELETE FROM chunks"))
            session.execute(text("DELETE FROM chunks_fts"))
        logger.info("store_cleared")

    def get_indexed_id_dates(self, source: str) -> dict[str, datetime | None]:
        with self._session() as session:
            rows = session.execute(
                text("SELECT source_id, updated_at FROM documents WHERE source_plugin=:source"),
                {"source": source},
            ).mappings().all()
        out: dict[str, datetime | None] = {}
        for row in rows:
            ts = row["updated_at"]
            out[row["source_id"]] = datetime.fromisoformat(ts) if ts else None
        return out

    def get_documents_raw(self, source: str) -> list[sqlite3.Row]:
        with self._session() as session:
            rows = session.execute(
                text("SELECT source_plugin, source_id, title, raw_text FROM documents WHERE source_plugin=:source"),
                {"source": source},
            ).mappings().all()
        return rows

    def delete_source_chunks(self, source: str) -> None:
        with self._session() as session:
            session.execute(text("DELETE FROM chunks WHERE source_plugin=:source"), {"source": source})
            session.execute(text("DELETE FROM chunks_fts WHERE source_plugin=:source"), {"source": source})

    def record_failure(self, source_plugin: str, source_id: str, error: str, error_type: str) -> None:
        now = datetime.utcnow().isoformat()
        with self._session() as session:
            existing = session.execute(
                select(SyncFailureModel).where(
                    SyncFailureModel.source_plugin == source_plugin,
                    SyncFailureModel.source_id == source_id,
                )
            ).scalar_one_or_none()
            if existing:
                existing.error_message = error
                existing.error_type = error_type
                existing.failed_at = now
                existing.retry_count = int(existing.retry_count or 0) + 1
                existing.last_retry_at = now
                return
            session.add(
                SyncFailureModel(
                    source_plugin=source_plugin,
                    source_id=source_id,
                    error_message=error,
                    error_type=error_type,
                    failed_at=now,
                    retry_count=0,
                    last_retry_at=None,
                )
            )

    def get_permanent_failures(self, source_plugin: str) -> set[str]:
        with self._session() as session:
            rows = session.execute(
                text(
                    "SELECT source_id FROM sync_failures "
                    "WHERE source_plugin=:source_plugin AND error_type='permanent'"
                ),
                {"source_plugin": source_plugin},
            ).mappings().all()
        return {row["source_id"] for row in rows}

    def clear_failure(self, source_plugin: str, source_id: str) -> None:
        with self._session() as session:
            session.execute(
                delete(SyncFailureModel).where(
                    SyncFailureModel.source_plugin == source_plugin,
                    SyncFailureModel.source_id == source_id,
                )
            )

    def list_failures(self, source_plugin: str | None = None) -> list[dict]:
        with self._session() as session:
            if source_plugin:
                rows = session.execute(
                    text(
                        "SELECT source_plugin, source_id, error_message, error_type, "
                        "failed_at, retry_count, last_retry_at "
                        "FROM sync_failures WHERE source_plugin=:source_plugin "
                        "ORDER BY failed_at DESC"
                    ),
                    {"source_plugin": source_plugin},
                ).mappings().all()
            else:
                rows = session.execute(
                    text(
                        "SELECT source_plugin, source_id, error_message, error_type, "
                        "failed_at, retry_count, last_retry_at "
                        "FROM sync_failures ORDER BY failed_at DESC"
                    )
                ).mappings().all()
        return [dict(row) for row in rows]

    def clear_failures(self, source_plugin: str | None = None, include_permanent: bool = False) -> int:
        with self._session() as session:
            if source_plugin and include_permanent:
                res = session.execute(
                    text("DELETE FROM sync_failures WHERE source_plugin=:source_plugin"),
                    {"source_plugin": source_plugin},
                )
            elif source_plugin:
                res = session.execute(
                    text(
                        "DELETE FROM sync_failures WHERE source_plugin=:source_plugin "
                        "AND error_type='transient'"
                    ),
                    {"source_plugin": source_plugin},
                )
            elif include_permanent:
                res = session.execute(text("DELETE FROM sync_failures"))
            else:
                res = session.execute(text("DELETE FROM sync_failures WHERE error_type='transient'"))
        return int(res.rowcount or 0)

    def status(self) -> list[dict]:
        with self._session() as session:
            doc_rows = session.execute(
                text("SELECT source_plugin, COUNT(*) as docs FROM documents GROUP BY source_plugin")
            ).mappings().all()
            failure_rows = session.execute(
                text(
                    "SELECT source_plugin, "
                    "COUNT(*) as sync_failures_total, "
                    "SUM(CASE WHEN error_type='transient' THEN 1 ELSE 0 END) as sync_failures_transient, "
                    "SUM(CASE WHEN error_type='permanent' THEN 1 ELSE 0 END) as sync_failures_permanent "
                    "FROM sync_failures GROUP BY source_plugin"
                )
            ).mappings().all()

        merged: dict[str, dict] = {}
        for row in doc_rows:
            merged[row["source_plugin"]] = {
                "source_plugin": row["source_plugin"],
                "docs": int(row["docs"]),
                "sync_failures_total": 0,
                "sync_failures_transient": 0,
                "sync_failures_permanent": 0,
            }
        for row in failure_rows:
            item = merged.setdefault(
                row["source_plugin"],
                {
                    "source_plugin": row["source_plugin"],
                    "docs": 0,
                    "sync_failures_total": 0,
                    "sync_failures_transient": 0,
                    "sync_failures_permanent": 0,
                },
            )
            item["sync_failures_total"] = int(row["sync_failures_total"] or 0)
            item["sync_failures_transient"] = int(row["sync_failures_transient"] or 0)
            item["sync_failures_permanent"] = int(row["sync_failures_permanent"] or 0)

        return [merged[name] for name in sorted(merged)]


def _apply_filters(results: list[SearchResult], filters: SearchFilters | None) -> list[SearchResult]:
    if not filters:
        return results
    out = []
    for item in results:
        if filters.source and item.source_plugin != filters.source:
            continue
        duration = item.duration_seconds or 0
        if filters.min_duration is not None and duration < filters.min_duration:
            continue
        if filters.max_duration is not None and duration > filters.max_duration:
            continue
        if filters.privacy_status is not None and item.privacy_status != filters.privacy_status:
            continue
        out.append(item)
    return out


def _apply_filters_dicts(items: list[dict], filters: SearchFilters | None) -> list[dict]:
    if not filters:
        return items
    out = []
    for item in items:
        if filters.source and item.get("source_plugin") != filters.source:
            continue
        duration = item.get("duration_seconds") or 0
        if filters.min_duration is not None and duration < filters.min_duration:
            continue
        if filters.max_duration is not None and duration > filters.max_duration:
            continue
        updated = item.get("updated_at", "") or ""
        if filters.since and updated[:10] < filters.since:
            continue
        if filters.until and updated[:10] > filters.until:
            continue
        raw_len = len(item.get("raw_text", "") or "")
        if filters.min_size is not None and raw_len < filters.min_size:
            continue
        if filters.max_size is not None and raw_len > filters.max_size:
            continue
        if filters.privacy_status is not None and item.get("privacy_status") != filters.privacy_status:
            continue
        out.append(item)
    return out
