from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
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

# HTML files live in corpus-agent/frontend/
_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def _html(name: str) -> HTMLResponse:
    path = _FRONTEND / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Frontend file missing: {path}")
    return HTMLResponse(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Frontend routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=RedirectResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui")


@app.get("/ui", response_class=HTMLResponse)
def ui_home() -> HTMLResponse:
    return _html("index.html")


@app.get("/ui/items", response_class=HTMLResponse)
def ui_items() -> HTMLResponse:
    return _html("items.html")


@app.get("/ui/search", response_class=HTMLResponse)
def ui_search() -> HTMLResponse:
    return _html("search.html")


@app.get("/ui/status", response_class=HTMLResponse)
def ui_status() -> HTMLResponse:
    return _html("status.html")


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

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
def items(source: str | None = None, limit: int = 50) -> list[dict]:
    return store.list_documents(source, limit)


@app.post("/sync")
def sync(req: SyncRequest) -> dict:
    if req.source not in plugins:
        raise HTTPException(status_code=400, detail="Unknown source")
    result = engine.sync(plugins[req.source], mode=req.mode, limit=req.limit)
    return {"source": result.source, "indexed": result.indexed, "skipped": result.skipped, "failures": len(result.failures)}


@app.post("/reindex")
def reindex(req: ReindexRequest) -> dict:
    if req.source not in plugins:
        raise HTTPException(status_code=400, detail="Unknown source")
    result = engine.reindex(plugins[req.source])
    return {"source": result.source, "documents": result.documents, "chunks": result.chunks}


@app.get("/search")
def search(q: str, mode: str = "keyword", limit: int = 5) -> list[dict]:
    if mode == "keyword":
        results = store.keyword_search(q, limit)
    elif mode == "semantic":
        vector = embedder.embed_texts([q])[0][1]
        results = store.semantic_search(vector, limit)
    else:
        raise HTTPException(status_code=400, detail="Invalid mode: use keyword or semantic")
    return [
        {"source_plugin": r.source_plugin, "source_id": r.source_id,
         "title": r.title, "excerpt": r.excerpt, "score": r.score}
        for r in results
    ]
