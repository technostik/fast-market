from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.config import load_config
from core.embedder import Embedder
from core.registry import build_plugins
from core.sync_engine import SyncEngine
from storage.sqlite_store import SQLiteStore

app = FastAPI(title="corpus-agent")

config = load_config()
store = SQLiteStore(config.get("db_path", ":memory:"))
embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
engine = SyncEngine(store, embedder)
plugins = build_plugins(config)


class SyncRequest(BaseModel):
    source: str
    mode: str = "new"
    limit: int = 10


class ReindexRequest(BaseModel):
    source: str


@app.get("/sources")
def sources() -> list[str]:
    return list(plugins.keys())


@app.get("/items")
def items(source: str | None = None, limit: int = 50) -> list[dict[str, object]]:
    return store.list_documents(source, limit)


@app.post("/sync")
def sync(req: SyncRequest) -> "SyncResult":
    if req.source not in plugins:
        raise HTTPException(status_code=400, detail="Unknown source")
    result = engine.sync(plugins[req.source], mode=req.mode, limit=req.limit)
    return result


@app.post("/reindex")
def reindex(req: ReindexRequest) -> "ReindexResult":
    if req.source not in plugins:
        raise HTTPException(status_code=400, detail="Unknown source")
    result = engine.reindex(plugins[req.source])
    return result


@app.get("/search")
def search(q: str, mode: str = "keyword", limit: int = 5) -> list["SearchResult"]:
    if mode == "keyword":
        results = store.keyword_search(q, limit)
    elif mode == "semantic":
        vector = embedder.embed_texts([q])[0][1]
        results = store.semantic_search(vector, limit)
    else:
        raise HTTPException(status_code=400, detail="Invalid mode")
    return results
