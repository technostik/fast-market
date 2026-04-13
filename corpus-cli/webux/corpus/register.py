from __future__ import annotations

from fastapi import APIRouter, Query

from common.webux.base import WebuxPluginManifest

router = APIRouter()


@router.get("/status")
def status() -> dict[str, list[dict]]:
    from storage.sqlalchemy_store import SQLAlchemyStore

    store = SQLAlchemyStore()
    return {"status": store.status()}


@router.get("/search")
def search(
    q: str = Query(""),
    mode: str = Query("keyword", pattern="^(keyword|semantic)$"),
    limit: int = Query(20, ge=1, le=200),
    source: str | None = Query(None),
) -> dict:
    from core.embedder import Embedder
    from storage.sqlalchemy_store import SQLAlchemyStore, SearchFilters

    store = SQLAlchemyStore()
    filters = SearchFilters(source=source)

    if not q.strip():
        return {"query": q, "mode": mode, "results": []}

    if mode == "semantic":
        embedder = Embedder()
        vector = embedder.embed_one(q)
        results = store.semantic_search(vector, limit=limit, filters=filters)
    else:
        results = store.keyword_search(q, limit=limit, filters=filters)

    return {
        "query": q,
        "mode": mode,
        "results": [
            {
                "handle": r.handle,
                "source_plugin": r.source_plugin,
                "source_id": r.source_id,
                "title": r.title,
                "excerpt": r.excerpt,
                "score": r.score,
            }
            for r in results
        ],
    }


@router.get("/list")
def list_docs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source: str | None = Query(None),
    order_by: str = Query("date", pattern="^(date|size|duration|title)$"),
) -> dict[str, list[dict]]:
    from storage.sqlalchemy_store import SQLAlchemyStore, SearchFilters

    store = SQLAlchemyStore()
    filters = SearchFilters(source=source)
    docs = store.list_documents_extended(
        source=source,
        filters=filters,
        order_by=order_by,
        limit=offset + limit,
    )
    return {"items": docs[offset : offset + limit]}


_HTML = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Corpus</title>
  <style>
    :root { --bg:#1a1a2e; --surface:#16213e; --accent:#0f3460; --text:#eee; --text-dim:#9ca3af; --border:#334155; --error:#f87171; }
    body { margin:0; padding:16px; background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; }
    .row { display:flex; gap:8px; margin-bottom:10px; }
    input, select, button { padding:8px; border:1px solid var(--border); background:var(--surface); color:var(--text); border-radius:6px; }
    input { flex:1; }
    .card { border:1px solid var(--border); border-radius:8px; padding:10px; background:var(--surface); margin-top:10px; }
    pre { white-space:pre-wrap; color:var(--text-dim); }
  </style>
</head>
<body>
  <h2>Corpus</h2>
  <div class="row"><input id="q" placeholder="Search..."/><select id="mode"><option value="keyword">keyword</option><option value="semantic">semantic</option></select><button id="searchBtn">Search</button></div>
  <div class="row"><button id="listBtn">List Docs</button><button id="statusBtn">Status</button></div>
  <div id="out" class="card"><pre>Ready.</pre></div>
<script>
const out = document.querySelector('#out pre');
const show = (v) => out.textContent = JSON.stringify(v, null, 2);

document.getElementById('searchBtn').onclick = async () => {
  const q = document.getElementById('q').value;
  const mode = document.getElementById('mode').value;
  const r = await fetch(`/api/corpus/search?q=${encodeURIComponent(q)}&mode=${mode}`);
  show(await r.json());
};
document.getElementById('listBtn').onclick = async () => {
  const r = await fetch('/api/corpus/list?limit=25&offset=0&order_by=date');
  show(await r.json());
};
document.getElementById('statusBtn').onclick = async () => {
  const r = await fetch('/api/corpus/status');
  show(await r.json());
};
</script>
</body>
</html>
"""


def register(config: dict) -> WebuxPluginManifest:
    del config
    return WebuxPluginManifest(
        name="corpus",
        tab_label="Corpus",
        tab_icon="📚",
        api_router=router,
        frontend_html=_HTML,
        order=10,
        lazy=True,
    )
