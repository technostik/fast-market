from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, select, delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from core.models import Chunk, Document, SearchResult
from core.paths import get_tool_data_dir
from storage.models import ChunkModel, DocumentModel

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
        db_url = self._build_db_url(path)
        self.engine = self._build_engine(path, db_url)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        self._run_migrations()
        self.conn = _CompatConnection(self)

    @staticmethod
    def _build_db_url(path: str) -> str:
        if path == ":memory:":
            return "sqlite+pysqlite:///:memory:"
        expanded = Path(path).expanduser()
        expanded.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+pysqlite:///{expanded}"

    @staticmethod
    def _build_engine(path: str, db_url: str) -> Engine:
        connect_args = {"check_same_thread": False}
        if path == ":memory:":
            return create_engine(
                db_url,
                future=True,
                connect_args=connect_args,
                poolclass=StaticPool,
                pool_pre_ping=True,
            )
        return create_engine(
            db_url,
            future=True,
            connect_args=connect_args,
            poolclass=QueuePool,
            pool_pre_ping=True,
        )

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

        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", self._build_db_url(self._path))
        try:
            command.upgrade(config, "head")
        except Exception as exc:  # fail loudly
            logger.error("db_migration_failed", error=str(exc), path=self._path)
            raise RuntimeError(f"Database migration failed for {self._path}") from exc
        logger.info("db_migration_complete", backend="sqlalchemy", path=self._path)

    @contextmanager
    def _session(self):
        session: Session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

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

    def status(self) -> list[dict]:
        with self._session() as session:
            rows = session.execute(
                text("SELECT source_plugin, COUNT(*) as docs FROM documents GROUP BY source_plugin")
            ).mappings().all()
        return [dict(row) for row in rows]


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
