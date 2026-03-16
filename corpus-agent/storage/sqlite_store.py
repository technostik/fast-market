from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import structlog

from core.models import Chunk, Document, SearchResult

logger = structlog.get_logger(__name__)


class SQLiteStore:
    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                source_plugin TEXT NOT NULL,
                source_id TEXT NOT NULL,
                title TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                url TEXT,
                updated_at TEXT,
                content_hash TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                UNIQUE(source_plugin, source_id)
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

    def upsert_document(self, document: Document, content_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT content_hash FROM documents WHERE source_plugin=? AND source_id=?",
            (document.source_plugin, document.source_id),
        ).fetchone()
        if row and row["content_hash"] == content_hash:
            return False
        self.conn.execute(
            """
            INSERT INTO documents(source_plugin, source_id, title, raw_text, url, updated_at, content_hash, metadata_json)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(source_plugin, source_id) DO UPDATE SET
                title=excluded.title,
                raw_text=excluded.raw_text,
                url=excluded.url,
                updated_at=excluded.updated_at,
                content_hash=excluded.content_hash,
                metadata_json=excluded.metadata_json
            """,
            (
                document.source_plugin,
                document.source_id,
                document.title,
                document.raw_text,
                document.url,
                document.updated_at.isoformat() if document.updated_at else None,
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

    def keyword_search(self, query: str, limit: int) -> list[SearchResult]:
        rows = self.conn.execute(
            """
            SELECT d.source_plugin, d.source_id, d.title, c.content
            FROM chunks_fts c
            JOIN documents d ON d.source_plugin=c.source_plugin AND d.source_id=c.source_id
            WHERE chunks_fts MATCH ?
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [
            SearchResult(r["source_plugin"], r["source_id"], r["title"], r["content"][:220], 1.0)
            for r in rows
        ]

    def semantic_search(self, query_vector: list[float], limit: int) -> list[SearchResult]:
        rows = self.conn.execute(
            "SELECT c.source_plugin, c.source_id, c.content, c.embedding_json, d.title FROM chunks c JOIN documents d ON d.source_plugin=c.source_plugin AND d.source_id=c.source_id"
        ).fetchall()
        q = [float(v) for v in query_vector]
        scored = []
        for row in rows:
            emb = [float(v) for v in json.loads(row["embedding_json"])]
            score = sum(a * b for a, b in zip(q, emb))
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SearchResult(row["source_plugin"], row["source_id"], row["title"], row["content"][:220], score)
            for score, row in scored[:limit]
        ]

    def list_documents(self, source: str | None = None, limit: int = 50) -> list[dict[str, object]]:
        if source:
            rows = self.conn.execute(
                "SELECT source_plugin, source_id, title, updated_at FROM documents WHERE source_plugin=? ORDER BY updated_at DESC LIMIT ?",
                (source, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT source_plugin, source_id, title, updated_at FROM documents ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_last_sync(self, source: str) -> datetime | None:
        row = self.conn.execute(
            "SELECT MAX(updated_at) AS ts FROM documents WHERE source_plugin=?", (source,)
        ).fetchone()
        if not row or not row["ts"]:
            return None
        return datetime.fromisoformat(row["ts"])

    def get_documents_raw(self, source: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT source_plugin, source_id, title, raw_text FROM documents WHERE source_plugin=?", (source,)
        ).fetchall()

    def delete_source_chunks(self, source: str) -> None:
        self.conn.execute("DELETE FROM chunks WHERE source_plugin=?", (source,))
        self.conn.execute("DELETE FROM chunks_fts WHERE source_plugin=?", (source,))
        self.conn.commit()

    def status(self) -> list[dict[str, object]]:
        rows = self.conn.execute(
            "SELECT source_plugin, COUNT(*) as docs FROM documents GROUP BY source_plugin"
        ).fetchall()
        return [dict(r) for r in rows]
