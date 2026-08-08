from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from common import structlog
from sqlalchemy import text, select, delete, func
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
from storage.models import (
    ChunkModel,
    DocumentModel,
    FieldDefinitionModel,
    PoolItemModel,
    SyncFailureModel,
)

logger = structlog.get_logger(__name__)

YOUTUBE_SHORT_MAX_SECONDS = 180
MAX_TRANSIENT_RETRIES = 3

# Field names become JSON object keys written into metadata_json and are used
# inside json_extract(metadata_json, '$.<name>') paths — keep them safe.
_FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


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
        missing_field: str | None = None,
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
        self.missing_field = missing_field

        if video_type == "short":
            self.max_duration = min(
                self.max_duration or 9999999, YOUTUBE_SHORT_MAX_SECONDS
            )
        elif video_type == "long":
            self.min_duration = max(
                self.min_duration or 0, YOUTUBE_SHORT_MAX_SECONDS + 1
            )


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
        with self.engine.connect() as conn:
            current_version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
        logger.info("db_migration_complete", backend="sqlalchemy", version=current_version)

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
                "updated_at": document.updated_at.isoformat()
                if document.updated_at
                else None,
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

    def replace_chunks(
        self, source_plugin: str, source_id: str, chunks: list[Chunk]
    ) -> None:
        with self._session() as session:
            session.execute(
                delete(ChunkModel).where(
                    ChunkModel.source_plugin == source_plugin,
                    ChunkModel.source_id == source_id,
                )
            )
            session.execute(
                text(
                    "DELETE FROM chunks_fts WHERE source_plugin = :source_plugin AND source_id = :source_id"
                ),
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
            row = (
                session.execute(
                    text(
                        "SELECT handle, source_plugin, source_id, title, raw_text, url, updated_at, "
                        "duration_seconds, privacy_status, metadata_json "
                        "FROM documents WHERE source_plugin=:source_plugin AND source_id=:source_id"
                    ),
                    {"source_plugin": source_plugin, "source_id": source_id},
                )
                .mappings()
                .first()
            )
            return self._row_to_doc_dict(row) if row else None

    def get_document_by_handle(self, handle: str) -> dict | None:
        with self._session() as session:
            row = (
                session.execute(
                    text(
                        "SELECT handle, source_plugin, source_id, title, raw_text, url, updated_at, "
                        "duration_seconds, privacy_status, metadata_json "
                        "FROM documents WHERE handle=:handle OR source_id=:handle"
                    ),
                    {"handle": handle},
                )
                .mappings()
                .first()
            )
            return self._row_to_doc_dict(row) if row else None

    def delete_document(self, source_plugin: str, source_id: str) -> bool:
        with self._session() as session:
            exists = session.execute(
                text(
                    "SELECT 1 FROM documents WHERE source_plugin=:source_plugin AND source_id=:source_id"
                ),
                {"source_plugin": source_plugin, "source_id": source_id},
            ).first()
            if not exists:
                return False
            session.execute(
                text(
                    "DELETE FROM documents WHERE source_plugin=:source_plugin AND source_id=:source_id"
                ),
                {"source_plugin": source_plugin, "source_id": source_id},
            )
            session.execute(
                text(
                    "DELETE FROM chunks WHERE source_plugin=:source_plugin AND source_id=:source_id"
                ),
                {"source_plugin": source_plugin, "source_id": source_id},
            )
            session.execute(
                text(
                    "DELETE FROM chunks_fts WHERE source_plugin=:source_plugin AND source_id=:source_id"
                ),
                {"source_plugin": source_plugin, "source_id": source_id},
            )
            logger.info(
                "document_deleted", source_plugin=source_plugin, source_id=source_id
            )
            return True

    def delete_document_by_handle(self, handle: str) -> bool:
        with self._session() as session:
            row = (
                session.execute(
                    text(
                        "SELECT source_plugin, source_id FROM documents WHERE handle=:handle OR source_id=:handle"
                    ),
                    {"handle": handle},
                )
                .mappings()
                .first()
            )
        if not row:
            return False
        return self.delete_document(row["source_plugin"], row["source_id"])

    def keyword_search(
        self, query: str, limit: int, filters: SearchFilters | None = None
    ) -> list[SearchResult]:
        with self._session() as session:
            rows = (
                session.execute(
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
                    {"query": f'"{query}"', "limit": limit * 5},
                )
                .mappings()
                .all()
            )
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

    def semantic_search(
        self,
        query_vector: list[float],
        limit: int,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
        with self._session() as session:
            rows = (
                session.execute(
                    text(
                        """
                    SELECT c.source_plugin, c.source_id, c.content, c.embedding_json,
                           d.handle, d.title, d.duration_seconds, d.privacy_status
                    FROM chunks c
                    JOIN documents d ON d.source_plugin=c.source_plugin AND d.source_id=c.source_id
                    """
                    )
                )
                .mappings()
                .all()
            )
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

    def list_documents(
        self,
        source: str | None = None,
        limit: int = 50,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        with self._session() as session:
            if source:
                rows = (
                    session.execute(
                        text(
                            "SELECT handle, source_plugin, source_id, title, url, updated_at, "
                            "duration_seconds, privacy_status, metadata_json "
                            "FROM documents WHERE source_plugin=:source ORDER BY updated_at DESC LIMIT :limit"
                        ),
                        {"source": source, "limit": limit * 5},
                    )
                    .mappings()
                    .all()
                )
            else:
                rows = (
                    session.execute(
                        text(
                            "SELECT handle, source_plugin, source_id, title, url, updated_at, "
                            "duration_seconds, privacy_status, metadata_json "
                            "FROM documents ORDER BY updated_at DESC LIMIT :limit"
                        ),
                        {"limit": limit * 5},
                    )
                    .mappings()
                    .all()
                )
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
                if filters.privacy_status == "non-public":
                    query += (
                        " AND (privacy_status IS NULL OR privacy_status != 'public')"
                    )
                else:
                    query += " AND privacy_status = :privacy_status"
                    params["privacy_status"] = filters.privacy_status
            if filters.missing_field:
                self._require_field_definition(filters.missing_field)
                query += (
                    f" AND json_extract(metadata_json, '$.{filters.missing_field}') "
                    "IS NULL"
                )

        order_field_map = {
            "date": "updated_at",
            "size": "LENGTH(raw_text)",
            "duration": "COALESCE(duration_seconds, 0)",
            "title": "title COLLATE NOCASE",
            "published": "json_extract(metadata_json, '$.published_at')",
        }
        if order_by.startswith("field:"):
            field_name = order_by.split(":", 1)[1]
            self._require_field_definition(field_name)
            order_field = f"json_extract(metadata_json, '$.{field_name}')"
        else:
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

    def count_documents(
        self,
        source: str | None = None,
        filters: SearchFilters | None = None,
    ) -> int:
        """Count documents matching the same filters as list_documents_extended."""
        query = "SELECT COUNT(*) FROM documents WHERE 1=1"
        params: dict[str, object] = {}

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
                if filters.privacy_status == "non-public":
                    query += (
                        " AND (privacy_status IS NULL OR privacy_status != 'public')"
                    )
                else:
                    query += " AND privacy_status = :privacy_status"
                    params["privacy_status"] = filters.privacy_status
            if filters.missing_field:
                self._require_field_definition(filters.missing_field)
                query += (
                    f" AND json_extract(metadata_json, '$.{filters.missing_field}') "
                    "IS NULL"
                )

        with self._session() as session:
            return int(session.execute(text(query), params).scalar() or 0)

    def list_sources(self) -> list[str]:
        """Distinct source_plugin values currently present in the documents table."""
        with self._session() as session:
            rows = session.execute(
                text("SELECT DISTINCT source_plugin FROM documents ORDER BY source_plugin")
            ).all()
        return [row[0] for row in rows]

    def delete_all(self) -> None:
        with self._session() as session:
            session.execute(text("DELETE FROM documents"))
            session.execute(text("DELETE FROM chunks"))
            session.execute(text("DELETE FROM chunks_fts"))
        logger.info("store_cleared")

    def get_indexed_id_dates(self, source: str) -> dict[str, datetime | None]:
        with self._session() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT source_id, updated_at FROM documents WHERE source_plugin=:source"
                    ),
                    {"source": source},
                )
                .mappings()
                .all()
            )
        out: dict[str, datetime | None] = {}
        for row in rows:
            ts = row["updated_at"]
            out[row["source_id"]] = datetime.fromisoformat(ts) if ts else None
        return out

    def get_documents_raw(self, source: str) -> list[sqlite3.Row]:
        with self._session() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT source_plugin, source_id, title, raw_text FROM documents WHERE source_plugin=:source"
                    ),
                    {"source": source},
                )
                .mappings()
                .all()
            )
        return rows

    def delete_source_chunks(self, source: str) -> None:
        with self._session() as session:
            session.execute(
                text("DELETE FROM chunks WHERE source_plugin=:source"),
                {"source": source},
            )
            session.execute(
                text("DELETE FROM chunks_fts WHERE source_plugin=:source"),
                {"source": source},
            )

    def record_failure(
        self,
        source_plugin: str,
        source_id: str,
        error: str,
        error_type: str,
        vault_path: str | None = None,
    ) -> None:
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
                existing.vault_path = vault_path
                if (
                    error_type == "transient"
                    and existing.retry_count >= MAX_TRANSIENT_RETRIES
                ):
                    logger.info(
                        "failure_upgraded_to_permanent",
                        source_plugin=source_plugin,
                        source_id=source_id,
                        retry_count=existing.retry_count,
                    )
                    existing.error_type = "permanent"
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
                    vault_path=vault_path,
                )
            )

    def get_permanent_failures(self, source_plugin: str) -> set[str]:
        with self._session() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT source_id FROM sync_failures "
                        "WHERE source_plugin=:source_plugin AND error_type='permanent'"
                    ),
                    {"source_plugin": source_plugin},
                )
                .mappings()
                .all()
            )
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
                rows = (
                    session.execute(
                        text(
                            "SELECT source_plugin, source_id, error_message, error_type, "
                            "failed_at, retry_count, last_retry_at, vault_path "
                            "FROM sync_failures WHERE source_plugin=:source_plugin "
                            "ORDER BY failed_at DESC"
                        ),
                        {"source_plugin": source_plugin},
                    )
                    .mappings()
                    .all()
                )
            else:
                rows = (
                    session.execute(
                        text(
                            "SELECT source_plugin, source_id, error_message, error_type, "
                            "failed_at, retry_count, last_retry_at, vault_path "
                            "FROM sync_failures ORDER BY failed_at DESC"
                        )
                    )
                    .mappings()
                    .all()
                )
        return [dict(row) for row in rows]

    def clear_failures(
        self,
        source_plugin: str | None = None,
        include_permanent: bool = False,
        include_blocked: bool = False,
    ) -> int:
        with self._session() as session:
            if include_blocked:
                # Clear ALL failures (transient + permanent + blocked)
                if source_plugin:
                    res = session.execute(
                        text(
                            "DELETE FROM sync_failures WHERE source_plugin=:source_plugin"
                        ),
                        {"source_plugin": source_plugin},
                    )
                else:
                    res = session.execute(text("DELETE FROM sync_failures"))
            elif source_plugin and include_permanent:
                res = session.execute(
                    text(
                        "DELETE FROM sync_failures WHERE source_plugin=:source_plugin"
                    ),
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
                res = session.execute(
                    text("DELETE FROM sync_failures WHERE error_type='transient'")
                )
        return int(res.rowcount or 0)

    def status(self) -> list[dict]:
        with self._session() as session:
            doc_rows = (
                session.execute(
                    text(
                        "SELECT source_plugin, COUNT(*) as docs FROM documents GROUP BY source_plugin"
                    )
                )
                .mappings()
                .all()
            )
            failure_rows = (
                session.execute(
                    text(
                        "SELECT source_plugin, "
                        "COUNT(*) as sync_failures_total, "
                        "SUM(CASE WHEN error_type='transient' THEN 1 ELSE 0 END) as sync_failures_transient, "
                        "SUM(CASE WHEN error_type='permanent' THEN 1 ELSE 0 END) as sync_failures_permanent "
                        "FROM sync_failures GROUP BY source_plugin"
                    )
                )
                .mappings()
                .all()
            )

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

    def full_status(self) -> list[dict]:
        """Rich per-source status: indexed docs, pool breakdown, failures.

        For YouTube the pool 'pending' count is split by privacy status so the
        caller knows which sync command applies to each group.
        """
        with self._session() as session:
            doc_rows = (
                session.execute(
                    text(
                        "SELECT source_plugin, COUNT(*) as cnt "
                        "FROM documents GROUP BY source_plugin"
                    )
                )
                .mappings()
                .all()
            )
            pool_rows = (
                session.execute(
                    text(
                        "SELECT source_plugin, source_id, status, metadata_json "
                        "FROM pool_items"
                    )
                )
                .mappings()
                .all()
            )
            failure_rows = (
                session.execute(
                    text(
                        "SELECT source_plugin, "
                        "SUM(CASE WHEN error_type='transient' THEN 1 ELSE 0 END) as transient, "
                        "SUM(CASE WHEN error_type='permanent' THEN 1 ELSE 0 END) as permanent "
                        "FROM sync_failures GROUP BY source_plugin"
                    )
                )
                .mappings()
                .all()
            )

        data: dict[str, dict] = {}

        for row in doc_rows:
            p = row["source_plugin"]
            _ensure(data, p)
            data[p]["indexed"] = int(row["cnt"])

        for row in pool_rows:
            p = row["source_plugin"]
            _ensure(data, p)
            status = row["status"]
            data[p]["pool"][status] = data[p]["pool"].get(status, 0) + 1

            if p == "youtube" and status == "pending":
                meta = json.loads(row["metadata_json"] or "{}")
                privacy = meta.get("privacy_status", "unknown")
                if privacy == "public":
                    data[p]["pool"]["pending_public"] = (
                        data[p]["pool"].get("pending_public", 0) + 1
                    )
                else:
                    data[p]["pool"]["pending_nonpublic"] = (
                        data[p]["pool"].get("pending_nonpublic", 0) + 1
                    )

        for row in failure_rows:
            p = row["source_plugin"]
            _ensure(data, p)
            data[p]["failures"]["transient"] = int(row["transient"] or 0)
            data[p]["failures"]["permanent"] = int(row["permanent"] or 0)

        return [data[k] for k in sorted(data)]

    # ── Pool methods ────────────────────────────────────────────────────────

    def upsert_pool_item(
        self,
        plugin_name: str,
        source_id: str,
        status: str,
        metadata: dict,
        added_at: str | None = None,
        synced_at: str | None = None,
    ) -> bool:
        """Insert or update a pool item. Returns True if newly inserted."""
        now = datetime.utcnow().isoformat()
        with self._session() as session:
            existing = session.execute(
                select(PoolItemModel).where(
                    PoolItemModel.source_plugin == plugin_name,
                    PoolItemModel.source_id == source_id,
                )
            ).scalar_one_or_none()
            if existing:
                existing.status = status
                existing.metadata_json = json.dumps(metadata)
                if synced_at:
                    existing.synced_at = synced_at
                return False
            session.add(
                PoolItemModel(
                    source_plugin=plugin_name,
                    source_id=source_id,
                    status=status,
                    metadata_json=json.dumps(metadata),
                    added_at=added_at or now,
                    synced_at=synced_at,
                )
            )
            return True

    def add_to_pool(self, items: list, plugin_name: str) -> int:
        """Batch-add ItemMeta items to pool as 'pending'. Skips already-pooled IDs.
        Returns count of newly added items."""
        now = datetime.utcnow().isoformat()
        existing_ids = set(self.get_pool_ids(plugin_name).keys())
        added = 0
        with self._session() as session:
            for item in items:
                if item.source_id in existing_ids:
                    continue
                session.add(
                    PoolItemModel(
                        source_plugin=plugin_name,
                        source_id=item.source_id,
                        status="pending",
                        metadata_json=json.dumps(item.metadata or {}),
                        added_at=now,
                        synced_at=None,
                    )
                )
                added += 1
        return added

    def remove_from_pool(self, plugin_name: str, source_id: str) -> bool:
        """Delete a pool item. Returns True if it existed."""
        with self._session() as session:
            res = session.execute(
                delete(PoolItemModel).where(
                    PoolItemModel.source_plugin == plugin_name,
                    PoolItemModel.source_id == source_id,
                )
            )
        return bool(res.rowcount)

    def get_pool_items(
        self,
        plugin_name: str | None = None,
        status: str | None = "pending",
        limit: int | None = None,
    ) -> list[dict]:
        """Return pool items as dicts, ordered by added_at ascending."""
        query = (
            "SELECT source_plugin, source_id, status, metadata_json, added_at, synced_at "
            "FROM pool_items WHERE 1=1"
        )
        params: dict = {}
        if plugin_name:
            query += " AND source_plugin=:plugin_name"
            params["plugin_name"] = plugin_name
        if status:
            query += " AND status=:status"
            params["status"] = status
        query += " ORDER BY added_at ASC"
        if limit:
            query += " LIMIT :limit"
            params["limit"] = limit
        with self._session() as session:
            rows = session.execute(text(query), params).mappings().all()
        return [
            {
                "source_plugin": r["source_plugin"],
                "source_id": r["source_id"],
                "status": r["status"],
                "metadata": json.loads(r["metadata_json"] or "{}"),
                "added_at": r["added_at"],
                "synced_at": r["synced_at"],
            }
            for r in rows
        ]

    def get_pool_ids(self, plugin_name: str) -> dict[str, str]:
        """Return {source_id: status} for all pool items of a plugin."""
        with self._session() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT source_id, status FROM pool_items WHERE source_plugin=:plugin_name"
                    ),
                    {"plugin_name": plugin_name},
                )
                .mappings()
                .all()
            )
        return {r["source_id"]: r["status"] for r in rows}

    def mark_pool_item(self, plugin_name: str, source_id: str, status: str) -> None:
        """Update status of a pool item, setting synced_at when status='synced'."""
        now = datetime.utcnow().isoformat()
        with self._session() as session:
            row = session.execute(
                select(PoolItemModel).where(
                    PoolItemModel.source_plugin == plugin_name,
                    PoolItemModel.source_id == source_id,
                )
            ).scalar_one_or_none()
            if row:
                row.status = status
                if status == "synced":
                    row.synced_at = now

    def pool_stats(self) -> list[dict]:
        """Return [{source_plugin, pending, synced, excluded, failed}] per plugin."""
        with self._session() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT source_plugin, status, COUNT(*) as cnt "
                        "FROM pool_items GROUP BY source_plugin, status"
                    )
                )
                .mappings()
                .all()
            )
        merged: dict[str, dict] = {}
        for row in rows:
            plugin = row["source_plugin"]
            if plugin not in merged:
                merged[plugin] = {
                    "source_plugin": plugin,
                    "pending": 0,
                    "synced": 0,
                    "excluded": 0,
                    "failed": 0,
                }
            merged[plugin][row["status"]] = int(row["cnt"] or 0)
        return [merged[k] for k in sorted(merged)]

    # ── Field definition (soft column) methods ──────────────────────────────

    @staticmethod
    def _validate_field_name(name: str) -> None:
        if not _FIELD_NAME_RE.match(name):
            raise ValueError(
                f"Invalid field name '{name}': must match {_FIELD_NAME_RE.pattern}"
            )

    def _get_field_row(self, session, name: str):
        return (
            session.execute(
                text(
                    "SELECT id, name, applies_to, description, created_at "
                    "FROM field_definitions WHERE name=:name"
                ),
                {"name": name},
            )
            .mappings()
            .first()
        )

    def create_field_definition(
        self,
        name: str,
        applies_to: str = "all",
        description: str | None = None,
    ) -> dict:
        """Declare a new soft field. Raises ValueError on invalid or duplicate name."""
        self._validate_field_name(name)
        with self._session() as session:
            existing = session.execute(
                text("SELECT 1 FROM field_definitions WHERE name=:name"),
                {"name": name},
            ).first()
            if existing:
                raise ValueError(f"Field '{name}' already defined")
            session.execute(
                text(
                    "INSERT INTO field_definitions (name, applies_to, description, created_at) "
                    "VALUES (:name, :applies_to, :description, :created_at)"
                ),
                {
                    "name": name,
                    "applies_to": applies_to,
                    "description": description,
                    "created_at": datetime.utcnow().isoformat(),
                },
            )
        return self.get_field_definition(name)

    def get_field_definition(self, name: str) -> dict | None:
        with self._session() as session:
            row = self._get_field_row(session, name)
        return dict(row) if row else None

    def list_field_definitions(self) -> list[dict]:
        with self._session() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT id, name, applies_to, description, created_at "
                        "FROM field_definitions ORDER BY name"
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def delete_field_definition(self, name: str) -> bool:
        """Remove a field declaration. Existing metadata_json values are kept."""
        with self._session() as session:
            res = session.execute(
                text("DELETE FROM field_definitions WHERE name=:name"),
                {"name": name},
            )
        return bool(res.rowcount)

    def _require_field_definition(self, name: str) -> None:
        if self.get_field_definition(name) is None:
            raise ValueError(
                f"Field '{name}' is not defined. Declare it with "
                f"`corpus field create --name {name}`."
            )

    def get_documents_missing_field(
        self,
        field_name: str,
        source: str | None = None,
        limit: int = 1000,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        """Documents whose metadata_json has no value for a declared field.

        Optional ``filters`` narrows by date range / duration (source is passed
        separately so the sync engine can apply its own per-source routing).
        """
        self._require_field_definition(field_name)
        query = (
            select(DocumentModel)
            .where(func.json_extract(DocumentModel.metadata_json, f"$.{field_name}").is_(None))
            .order_by(DocumentModel.updated_at.desc())
        )
        if source:
            query = query.where(DocumentModel.source_plugin == source)
        if filters:
            if filters.since:
                query = query.where(DocumentModel.updated_at >= f"{filters.since}T00:00:00")
            if filters.until:
                query = query.where(DocumentModel.updated_at <= f"{filters.until}T23:59:59")
            if filters.min_duration is not None:
                query = query.where(
                    DocumentModel.duration_seconds >= filters.min_duration
                )
            if filters.max_duration is not None:
                query = query.where(
                    DocumentModel.duration_seconds <= filters.max_duration
                )
        query = query.limit(limit)
        with self._session() as session:
            rows = session.scalars(query).all()
            docs = [self._row_to_doc_dict_model(row) for row in rows]
        return docs

    def set_document_field(
        self,
        source_plugin: str,
        source_id: str,
        field_name: str,
        value: object,
    ) -> bool:
        """Write a declared field into a document's metadata_json.

        Raises ValueError for undeclared field names. Returns False when the
        document does not exist.
        """
        self._require_field_definition(field_name)
        with self._session() as session:
            row = (
                session.execute(
                    text(
                        "SELECT metadata_json FROM documents "
                        "WHERE source_plugin=:source_plugin AND source_id=:source_id"
                    ),
                    {"source_plugin": source_plugin, "source_id": source_id},
                )
                .scalar_one_or_none()
            )
            if row is None:
                return False
            metadata = json.loads(row or "{}")
            metadata[field_name] = value
            session.execute(
                text(
                    "UPDATE documents SET metadata_json=:metadata_json "
                    "WHERE source_plugin=:source_plugin AND source_id=:source_id"
                ),
                {
                    "metadata_json": json.dumps(metadata),
                    "source_plugin": source_plugin,
                    "source_id": source_id,
                },
            )
            return True

    @staticmethod
    def _row_to_doc_dict_model(row: DocumentModel) -> dict:
        return {
            "handle": row.handle,
            "source_plugin": row.source_plugin,
            "source_id": row.source_id,
            "title": row.title,
            "raw_text": row.raw_text,
            "url": row.url,
            "updated_at": row.updated_at,
            "duration_seconds": row.duration_seconds,
            "privacy_status": row.privacy_status,
            "metadata": json.loads(row.metadata_json or "{}"),
        }


def _apply_filters(
    results: list[SearchResult], filters: SearchFilters | None
) -> list[SearchResult]:
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
        if filters.privacy_status is not None:
            if filters.privacy_status == "non-public":
                if item.privacy_status == "public":
                    continue
            elif item.privacy_status != filters.privacy_status:
                continue
        out.append(item)
    return out


def _apply_filters_dicts(
    items: list[dict], filters: SearchFilters | None
) -> list[dict]:
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
        privacy = item.get("privacy_status")
        if filters.privacy_status is not None:
            if filters.privacy_status == "non-public":
                if privacy == "public":
                    continue
            elif privacy != filters.privacy_status:
                continue
        if filters.missing_field:
            metadata = item.get("metadata") or {}
            if filters.missing_field in metadata:
                continue
        out.append(item)
    return out


def _ensure(data: dict, plugin: str) -> None:
    if plugin not in data:
        data[plugin] = {
            "source_plugin": plugin,
            "indexed": 0,
            "pool": {"pending": 0, "synced": 0, "failed": 0, "excluded": 0},
            "failures": {"transient": 0, "permanent": 0},
        }
