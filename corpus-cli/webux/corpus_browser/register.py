from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

router = APIRouter()


@router.get("/browse")
def browse(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    source: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    min_duration: Optional[int] = Query(None, ge=0),
    max_duration: Optional[int] = Query(None, ge=0),
    order_by: str = Query("date", pattern="^(date|size|duration|title)$"),
    order_desc: bool = Query(True),
):
    from storage.sqlalchemy_store import SQLAlchemyStore, SearchFilters
    from sqlalchemy import text

    store = SQLAlchemyStore()
    filters = SearchFilters(source=source, since=since, until=until, min_duration=min_duration, max_duration=max_duration)

    # Get total count
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

    with store._session() as session:
        total_result = session.execute(text(query), params).scalar()
        total = total_result or 0

    docs = store.list_documents_extended(
        source=source,
        filters=filters,
        order_by=order_by,
        reverse=not order_desc,
        limit=offset + limit,
    )
    return {"items": docs[offset: offset + limit], "total": total}


@router.get("/document/{handle}")
def get_document(handle: str):
    from storage.sqlalchemy_store import SQLAlchemyStore

    store = SQLAlchemyStore()
    doc = store.get_document_by_handle(handle)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/sources")
def get_sources():
    from storage.sqlalchemy_store import SQLAlchemyStore
    from sqlalchemy import text

    store = SQLAlchemyStore()
    with store._session() as session:
        result = session.execute(text("SELECT DISTINCT source_plugin FROM documents"))
        sources = [row[0] for row in result.fetchall()]
    return {"sources": sources}


@router.get("/search")
def search(
    q: str = Query(""),
    mode: str = Query("keyword", pattern="^(keyword|semantic)$"),
    limit: int = Query(500, ge=1, le=500),
    source: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    min_duration: Optional[int] = Query(None, ge=0),
    max_duration: Optional[int] = Query(None, ge=0),
):
    from core.embedder import Embedder
    from storage.sqlalchemy_store import SQLAlchemyStore, SearchFilters

    store = SQLAlchemyStore()
    filters = SearchFilters(source=source, since=since, until=until, min_duration=min_duration, max_duration=max_duration)

    if not q.strip():
        return {"query": q, "mode": mode, "results": []}

    if mode == "semantic":
        embedder = Embedder()
        vector = embedder.embed_texts([q])[0][1]
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
                "duration": r.duration_seconds,
            }
            for r in results
        ],
    }


@router.get("/stats")
def stats():
    from storage.sqlalchemy_store import SQLAlchemyStore

    store = SQLAlchemyStore()
    return {"stats": store.status()}


_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Corpus Browser</title>
  <style>
    :root { --bg:#1a1a2e; --surface:#16213e; --accent:#0f3460; --text:#eee; --text-dim:#9ca3af; --border:#334155; --error:#f87171; --success:#10b981; }
    body { margin:0; padding:16px; background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; display:flex; flex-direction:column; height:100vh; }
    .header { display:flex; gap:8px; margin-bottom:16px; align-items:center; }
    input, select, button { padding:8px; border:1px solid var(--border); background:var(--surface); color:var(--text); border-radius:6px; }
    input[type="date"] { width:120px; }
    .filters { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
    .sidebar { width:250px; flex-shrink:0; margin-right:16px; }
    .sidebar h3 { margin-top:0; }
    .checkbox-group { margin-bottom:8px; }
    .checkbox-group label { display:block; margin:2px 0; }
    .main { flex:1; display:flex; flex-direction:column; }
    .list { flex:1; overflow-y:auto; }
    .doc-card { border:1px solid var(--border); border-radius:8px; padding:12px; margin-bottom:8px; background:var(--surface); cursor:pointer; }
    .doc-card:hover { border-color:var(--accent); }
    .doc-title { font-weight:bold; margin-bottom:4px; }
    .doc-meta { font-size:0.9em; color:var(--text-dim); }
    .pagination { display:flex; justify-content:center; gap:8px; margin-top:16px; }
    .preview { position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); display:none; z-index:1000; }
    .preview-content { background:var(--surface); margin:5% auto; width:80%; max-height:80%; overflow-y:auto; padding:20px; border-radius:8px; }
    .close-btn { float:right; cursor:pointer; font-size:1.5em; }
    pre { white-space:pre-wrap; color:var(--text); }
    .loading { text-align:center; padding:20px; }
  </style>
</head>
<body>
  <div class="header">
    <input id="q" placeholder="Search..."/>
    <select id="mode">
      <option value="keyword">keyword</option>
      <option value="semantic">semantic</option>
    </select>
    <button id="searchBtn">Search</button>
    <button id="browseBtn">Browse All</button>
    <button id="statsBtn">Stats</button>
  </div>
  <div class="filters">
    <select id="sourceFilter">
      <option value="">All Sources</option>
    </select>
    <input type="date" id="since" placeholder="Since date"/>
    <input type="date" id="until" placeholder="Until date"/>
    <input type="number" id="minDuration" placeholder="Min duration (s)" min="0"/>
    <input type="number" id="maxDuration" placeholder="Max duration (s)" min="0"/>
    <select id="orderBy">
      <option value="date">Date</option>
      <option value="size">Size</option>
      <option value="duration">Duration</option>
      <option value="title">Title</option>
    </select>
    <label><input type="checkbox" id="orderDesc" checked/> Desc</label>
  </div>
  <div class="main">
    <div class="list" id="list">
      <div class="loading">Loading...</div>
    </div>
    <div class="pagination" id="pagination"></div>
  </div>
  <div class="preview" id="preview">
    <div class="preview-content">
      <span class="close-btn" onclick="closePreview()">×</span>
      <h2 id="previewTitle"></h2>
      <div id="previewMeta"></div>
      <pre id="previewContent"></pre>
    </div>
  </div>
<script>
let currentOffset = 0;
let currentLimit = 20;
let currentResults = [];
let currentPage = 0;
let isSearchMode = false;
let currentFilters = {};

function show(data) {
  const list = document.getElementById('list');
  list.innerHTML = '';
  if (data.items) {
    data.items.forEach(item => {
      const card = document.createElement('div');
      card.className = 'doc-card';
      card.innerHTML = `
        <div class="doc-title">${item.title || 'Untitled'}</div>
        <div class="doc-meta">
          ${item.source_plugin} | ${item.date ? new Date(item.date).toLocaleDateString() : ''} | ${item.duration || 0}s
        </div>
        <div>${item.excerpt || ''}</div>
      `;
      card.onclick = () => showPreview(item.handle);
      list.appendChild(card);
    });
  } else if (data.results) {
    data.results.forEach(result => {
      const card = document.createElement('div');
      card.className = 'doc-card';
      card.innerHTML = `
        <div class="doc-title">${result.title || 'Untitled'}</div>
        <div class="doc-meta">
          ${result.source_plugin} | Score: ${result.score?.toFixed(2) || ''} | ${result.duration || 0}s
        </div>
        <div>${result.excerpt || ''}</div>
      `;
      card.onclick = () => showPreview(result.handle);
      list.appendChild(card);
    });
  } else {
    list.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
  }
}

function showPage(page) {
  const start = page * currentLimit;
  const end = start + currentLimit;
  const pageResults = currentResults.slice(start, end);
  show({results: pageResults});
}

async function loadSources() {
  const r = await fetch('/api/corpus_browser/sources');
  const data = await r.json();
  const select = document.getElementById('sourceFilter');
  data.sources.forEach(source => {
    const option = document.createElement('option');
    option.value = source;
    option.textContent = source;
    select.appendChild(option);
  });
}

async function browse(offset = 0) {
  const params = new URLSearchParams({
    limit: currentLimit,
    offset,
    order_by: document.getElementById('orderBy').value,
    order_desc: document.getElementById('orderDesc').checked,
  });
  const source = document.getElementById('sourceFilter').value;
  if (source) params.set('source', source);
  const since = document.getElementById('since').value;
  if (since) params.set('since', since);
  const until = document.getElementById('until').value;
  if (until) params.set('until', until);
  const minDuration = document.getElementById('minDuration').value;
  if (minDuration) params.set('min_duration', minDuration);
  const maxDuration = document.getElementById('maxDuration').value;
  if (maxDuration) params.set('max_duration', maxDuration);
  const r = await fetch(`/api/corpus_browser/browse?${params}`);
  const data = await r.json();
  currentOffset = offset;
  isSearchMode = false;
  show(data);
  updatePagination(data.total);
}

async function search() {
  const q = document.getElementById('q').value;
  const mode = document.getElementById('mode').value;
  const params = new URLSearchParams({
    q,
    mode,
    limit: 500,
  });
  const source = document.getElementById('sourceFilter').value;
  if (source) params.set('source', source);
  const since = document.getElementById('since').value;
  if (since) params.set('since', since);
  const until = document.getElementById('until').value;
  if (until) params.set('until', until);
  const minDuration = document.getElementById('minDuration').value;
  if (minDuration) params.set('min_duration', minDuration);
  const maxDuration = document.getElementById('maxDuration').value;
  if (maxDuration) params.set('max_duration', maxDuration);
  const r = await fetch(`/api/corpus_browser/search?${params}`);
  const data = await r.json();
  currentResults = data.results || [];
  currentPage = 0;
  isSearchMode = true;
  showPage(currentPage);
  updatePagination(currentResults.length);
}

async function showStats() {
  const r = await fetch('/api/corpus_browser/stats');
  const data = await r.json();
  show(data);
  document.getElementById('pagination').innerHTML = '';
}

async function showPreview(handle) {
  const r = await fetch(`/api/corpus_browser/document/${handle}`);
  const doc = await r.json();
  document.getElementById('previewTitle').textContent = doc.title || 'Untitled';
  let meta = `Source: ${doc.source_plugin} | Date: ${doc.date ? new Date(doc.date).toLocaleDateString() : ''} | Duration: ${doc.duration || 0}s`;
  if (doc.url) {
    meta += `<br>Original: <a href="${doc.url}" target="_blank">${doc.url}</a>`;
  }
  document.getElementById('previewMeta').innerHTML = meta;
  document.getElementById('previewContent').textContent = doc.raw_text || '';
  document.getElementById('preview').style.display = 'block';
}

function closePreview() {
  document.getElementById('preview').style.display = 'none';
}

function updatePagination(total) {
  const pagination = document.getElementById('pagination');
  pagination.innerHTML = '';
  if (total > currentLimit) {
    const pages = Math.ceil(total / currentLimit);
    const current = isSearchMode ? currentPage : Math.floor(currentOffset / currentLimit);
    const maxButtons = 10;
    let start = Math.max(0, current - Math.floor(maxButtons / 2));
    let end = Math.min(pages, start + maxButtons);
    start = Math.max(0, end - maxButtons);

    // Prev button
    if (current > 0) {
      const prevBtn = document.createElement('button');
      prevBtn.textContent = '←';
      prevBtn.onclick = () => {
        if (isSearchMode) {
          currentPage--;
          showPage(currentPage);
          updatePagination(total);
        } else {
          browse(currentOffset - currentLimit);
        }
      };
      pagination.appendChild(prevBtn);
    }

    // First page if not in range
    if (start > 0) {
      const firstBtn = document.createElement('button');
      firstBtn.textContent = '1';
      firstBtn.onclick = () => {
        if (isSearchMode) {
          currentPage = 0;
          showPage(0);
          updatePagination(total);
        } else {
          browse(0);
        }
      };
      pagination.appendChild(firstBtn);
      if (start > 1) {
        const ellipsis = document.createElement('span');
        ellipsis.textContent = '...';
        pagination.appendChild(ellipsis);
      }
    }

    // Page buttons
    for (let i = start; i < end; i++) {
      const btn = document.createElement('button');
      btn.textContent = i + 1;
      btn.onclick = () => {
        if (isSearchMode) {
          currentPage = i;
          showPage(i);
          updatePagination(total);
        } else {
          browse(i * currentLimit);
        }
      };
      if (i === current) btn.disabled = true;
      pagination.appendChild(btn);
    }

    // Last page if not in range
    if (end < pages) {
      if (end < pages - 1) {
        const ellipsis = document.createElement('span');
        ellipsis.textContent = '...';
        pagination.appendChild(ellipsis);
      }
      const lastBtn = document.createElement('button');
      lastBtn.textContent = pages;
      lastBtn.onclick = () => {
        if (isSearchMode) {
          currentPage = pages - 1;
          showPage(pages - 1);
          updatePagination(total);
        } else {
          browse((pages - 1) * currentLimit);
        }
      };
      pagination.appendChild(lastBtn);
    }

    // Next button
    if (current < pages - 1) {
      const nextBtn = document.createElement('button');
      nextBtn.textContent = '→';
      nextBtn.onclick = () => {
        if (isSearchMode) {
          currentPage++;
          showPage(currentPage);
          updatePagination(total);
        } else {
          browse(currentOffset + currentLimit);
        }
      };
      pagination.appendChild(nextBtn);
    }
  }
}

document.getElementById('searchBtn').onclick = search;
document.getElementById('browseBtn').onclick = () => browse(0);
document.getElementById('statsBtn').onclick = showStats;

// Load sources and initial browse on load
loadSources();
browse(0);
</script>
</body>
</html>
"""


def register(config: dict) -> WebuxPluginManifest:
    from common.webux.base import WebuxPluginManifest
    del config
    return WebuxPluginManifest(
        name="corpus_browser",
        tab_label="Corpus Browser",
        tab_icon="🔍",
        api_router=router,
        frontend_html=_HTML,
        order=20,
        lazy=True,
    )