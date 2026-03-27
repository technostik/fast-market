from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Document:
    source_plugin: str
    source_id: str
    title: str
    raw_text: str
    handle: str = ""  # stable slug handle, e.g. yt-my-video-a3f2
    url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    duration_seconds: int | None = None  # YouTube: video duration; Obsidian: None
    privacy_status: str | None = (
        None  # YouTube: "public" | "private" | "unlisted"; Obsidian: None
    )
    metadata: dict[str, object] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Chunk:
    source_plugin: str
    source_id: str
    chunk_index: int
    content: str
    content_hash: str
    embedding: list[float]
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class SyncFailure:
    source_id: str
    error: str


@dataclass(slots=True)
class SyncResult:
    source: str
    processed: int
    indexed: int
    skipped: int
    failures: list[SyncFailure] = field(default_factory=list)
    warning: str | None = None


@dataclass(slots=True)
class ReindexResult:
    source: str
    documents: int
    chunks: int


@dataclass(slots=True)
class SearchResult:
    source_plugin: str
    source_id: str
    handle: str
    title: str
    excerpt: str
    score: float
    duration_seconds: int | None = None
    privacy_status: str | None = (
        None  # YouTube: "public" | "private" | "unlisted"; Obsidian: None
    )
