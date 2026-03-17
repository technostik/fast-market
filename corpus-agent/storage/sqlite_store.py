from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import structlog

from core.models import Chunk, Document, SearchResult
from core.paths import get_tool_data_dir

logger = structlog.get_logger(__name__)

YOUTUBE_SHORT_MAX_SECONDS = 60


class SQLiteStore:
    def __init__(self, path: str | None = None) -> None:
        if path is None:
            path = str(get_tool_data_dir("corpus") / "corpus.db")
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
        self._migrate()

    def _init_db(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                handle TEXT NOT NULL,
                source_plugin TEXT NOT NULL,
                source_id TEXT NOT NULL,
                title TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                url TEXT,
                updated_at TEXT,
                duration_seconds INTEGER,
                privacy_status TEXT,
                content_hash TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                UNIQUE(source_plugin, source_id),
                UNIQUE(handle)
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY,
                source_plugin TEXT NOT NULL,
                source_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                UNIQUE(source_plugin, source_id, chunk_index)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                source_plugin, source_id, content
            );
            """
        )
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after the initial schema — safe to run on every start."""
        existing = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(documents)").fetchall()
        }
        if "privacy_status" not in existing:
            self.conn.execute("ALTER TABLE documents ADD COLUMN privacy_status TEXT")
            self.conn.commit()
            logger.info("db_migrated", added_column="privacy_status")

    def upsert_document(self, document: Document, content_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT content_hash FROM documents WHERE source_plugin=? AND source_id=?",
            (document.source_plugin, document.source_id),
        ).fetchone()
        if row and row["content_hash"] == content_hash:
            return False
        self.conn.execute(
            """
            INSERT INTO documents(
                handle, source_plugin, source_id, title, raw_text, url, updated_at,
                duration_seconds, privacy_status, content_hash, metadata_json
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_plugin, source_id) DO UPDATE SET
                handle=excluded.handle,
                title=excluded.title,
                raw_text=excluded.raw_text,
                url=excluded.url,
                updated_at=excluded.updated_at,
                duration_seconds=excluded.duration_seconds,
                privacy_status=excluded.privacy_status,
                content_hash=excluded.content_hash,
                metadata_json=excluded.metadata_json
            """,
            (
                document.handle,
                document.source_plugin,
                document.source_id,
                document.title,
                document.raw_text,
                document.url,
                document.updated_at.isoformat() if document.updated_at else None,
                document.duration_seconds,
                document.privacy_status,
                content_hash,
                json.dumps(document.metadata),
            ),
        )
        self.conn.commit()
        return True

    def replace_chunks(self, source_plugin: str, source_id: str, chunks: list[Chunk]) -> None:
        self.conn.execute("DELETE FROM chunks WHERE source_plugin=? AND source_id=?", (source_plugin, source_id))
        self.conn.execute("DELETE FROM chunks_fts WHERE source_plugin=? AND source_id=?", (source_plugin, source_id))
        for chunk in chunks:
            self.conn.execute(
                """
                INSERT INTO chunks(source_plugin, source_id, chunk_index, content, content_hash, embedding_json, metadata_json)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    chunk.source_plugin,
                    chunk.source_id,
                    chunk.chunk_index,
                    chunk.content,
                    chunk.content_hash,
                    json.dumps(chunk.embedding),
                    json.dumps(chunk.metadata),
                ),
            )
            self.conn.execute(
                "INSERT INTO chunks_fts(source_plugin, source_id, content) VALUES(?,?,?)",
                (chunk.source_plugin, chunk.source_id, chunk.content),
            )
        self.conn.commit()

    def _row_to_doc_dict(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        if "metadata_json" in d:
            d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
        return d

    def get_document(self, source_plugin: str, source_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT handle, source_plugin, source_id, title, raw_text, url, updated_at, "
            "duration_seconds, privacy_status, metadata_json "
            "FROM documents WHERE source_plugin=? AND source_id=?",
            (source_plugin, source_id),
        ).fetchone()
        return self._row_to_doc_dict(row) if row else None

    def get_document_by_handle(self, handle: str) -> dict | None:
        """Resolve by handle OR source_id (fallback for convenience)."""
        row = self.conn.execute(
            "SELECT handle, source_plugin, source_id, title, raw_text, url, updated_at, "
            "duration_seconds, privacy_status, metadata_json "
            "FROM documents WHERE handle=? OR source_id=?",
            (handle, handle),
        ).fetchone()
        return self._row_to_doc_dict(row) if row else None

    def delete_document(self, source_plugin: str, source_id: str) -> bool:
        row = self.conn.execute(
            "SELECT id FROM documents WHERE source_plugin=? AND source_id=?",
            (source_plugin, source_id),
        ).fetchone()
        if not row:
            return False
        self.conn.execute("DELETE FROM documents WHERE source_plugin=? AND source_id=?", (source_plugin, source_id))
        self.conn.execute("DELETE FROM chunks WHERE source_plugin=? AND source_id=?", (source_plugin, source_id))
        self.conn.execute("DELETE FROM chunks_fts WHERE source_plugin=? AND source_id=?", (source_plugin, source_id))
        self.conn.commit()
        logger.info("document_deleted", source_plugin=source_plugin, source_id=source_id)
        return True

    def delete_document_by_handle(self, handle: str) -> bool:
        row = self.conn.execute(
            "SELECT source_plugin, source_id FROM documents WHERE handle=? OR source_id=?",
            (handle, handle),
        ).fetchone()
        if not row:
            return False
        return self.delete_document(row["source_plugin"], row["source_id"])

    def keyword_search(
        self,
        query: str,
        limit: int,
        filters: "SearchFilters | None" = None,
    ) -> list[SearchResult]:
        rows = self.conn.execute(
            """
            SELECT d.handle, d.source_plugin, d.source_id, d.title, d.duration_seconds,
                   d.privacy_status, c.content
            FROM chunks_fts c
            JOIN documents d ON d.source_plugin=c.source_plugin AND d.source_id=c.source_id
            WHERE chunks_fts MATCH ?
            LIMIT ?
            """,
            (query, limit * 5),  # over-fetch then filter
        ).fetchall()
        results = [
            SearchResult(
                source_plugin=r["source_plugin"],
                source_id=r["source_id"],
                handle=r["handle"],
                title=r["title"],
                excerpt=r["content"][:220],
                score=1.0,
                duration_seconds=r["duration_seconds"],
                privacy_status=r["privacy_status"],
            )
            for r in rows
        ]
        return _apply_filters(results, filters)[:limit]

    def semantic_search(
        self,
        query_vector: list[float],
        limit: int,
        filters: "SearchFilters | None" = None,
    ) -> list[SearchResult]:
        rows = self.conn.execute(
            """
            SELECT c.source_plugin, c.source_id, c.content, c.embedding_json,
                   d.handle, d.title, d.duration_seconds, d.privacy_status
            FROM chunks c
            JOIN documents d ON d.source_plugin=c.source_plugin AND d.source_id=c.source_id
            """
        ).fetchall()
        q = [float(v) for v in query_vector]
        scored = []
        for row in rows:
            emb = [float(v) for v in json.loads(row["embedding_json"])]
            score = sum(a * b for a, b in zip(q, emb))
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)

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
        filters: "SearchFilters | None" = None,
    ) -> list[dict]:
        if source:
            rows = self.conn.execute(
                "SELECT handle, source_plugin, source_id, title, url, updated_at, "
                "duration_seconds, privacy_status, metadata_json "
                "FROM documents WHERE source_plugin=? ORDER BY updated_at DESC LIMIT ?",
                (source, limit * 5),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT handle, source_plugin, source_id, title, url, updated_at, "
                "duration_seconds, privacy_status, metadata_json "
                "FROM documents ORDER BY updated_at DESC LIMIT ?",
                (limit * 5,),
            ).fetchall()

        items = [self._row_to_doc_dict(r) for r in rows]
        if filters:
            items = _apply_filters_dicts(items, filters)
        return items[:limit]

    def delete_all(self) -> None:
        self.conn.executescript("DELETE FROM documents; DELETE FROM chunks; DELETE FROM chunks_fts;")
        self.conn.commit()
        logger.info("store_cleared")

    def get_indexed_id_dates(self, source: str) -> dict[str, datetime | None]:
        """Return {source_id: updated_at} for every indexed document of this source.

        Plugins use this as their incremental cursor:
        - YouTube: checks source_id presence to skip already-indexed videos.
        - Obsidian: checks both presence (new file?) and updated_at vs current mtime
          (modified file?), skipping only when known AND mtime unchanged.
        """
        rows = self.conn.execute(
            "SELECT source_id, updated_at FROM documents WHERE source_plugin=?", (source,)
        ).fetchall()
        out: dict[str, datetime | None] = {}
        for row in rows:
            ts = row["updated_at"]
            out[row["source_id"]] = datetime.fromisoformat(ts) if ts else None
        return out

    def get_documents_raw(self, source: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT source_plugin, source_id, title, raw_text FROM documents WHERE source_plugin=?", (source,)
        ).fetchall()

    def delete_source_chunks(self, source: str) -> None:
        self.conn.execute("DELETE FROM chunks WHERE source_plugin=?", (source,))
        self.conn.execute("DELETE FROM chunks_fts WHERE source_plugin=?", (source,))
        self.conn.commit()

    def status(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT source_plugin, COUNT(*) as docs FROM documents GROUP BY source_plugin"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Search filters
# ---------------------------------------------------------------------------

class SearchFilters:
    def __init__(
        self,
        source: str | None = None,
        min_duration: int | None = None,
        max_duration: int | None = None,
        video_type: str | None = None,       # "short" | "long"
        since: str | None = None,            # ISO date string YYYY-MM-DD
        until: str | None = None,            # ISO date string YYYY-MM-DD
        min_size: int | None = None,         # min raw_text chars (obsidian)
        max_size: int | None = None,
        privacy_status: str | None = None,   # "public" | "unlisted" | "private" | "unknown"
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

        # Resolve video_type into duration bounds
        if video_type == "short":
            self.max_duration = min(self.max_duration or 9999999, YOUTUBE_SHORT_MAX_SECONDS)
        elif video_type == "long":
            self.min_duration = max(self.min_duration or 0, YOUTUBE_SHORT_MAX_SECONDS + 1)


def _apply_filters(results: list[SearchResult], filters: "SearchFilters | None") -> list[SearchResult]:
    if not filters:
        return results
    out = []
    for r in results:
        if filters.source and r.source_plugin != filters.source:
            continue
        dur = r.duration_seconds or 0
        if filters.min_duration is not None and dur < filters.min_duration:
            continue
        if filters.max_duration is not None and dur > filters.max_duration:
            continue
        if filters.privacy_status is not None and r.privacy_status != filters.privacy_status:
            continue
        out.append(r)
    return out


def _apply_filters_dicts(items: list[dict], filters: "SearchFilters | None") -> list[dict]:
    if not filters:
        return items
    out = []
    for item in items:
        if filters.source and item.get("source_plugin") != filters.source:
            continue
        dur = item.get("duration_seconds") or 0
        if filters.min_duration is not None and dur < filters.min_duration:
            continue
        if filters.max_duration is not None and dur > filters.max_duration:
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
