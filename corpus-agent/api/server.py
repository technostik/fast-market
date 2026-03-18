from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from common.core.config import load_config
from common.core.registry import discover_commands, discover_plugins

app = FastAPI(title="corpus-agent")
_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
_TOOL_ROOT = Path(__file__).resolve().parent.parent


@app.on_event("startup")
def _run_startup_migrations():
    from storage.sqlalchemy_store import SQLAlchemyStore

    _ = SQLAlchemyStore()


def _html(name: str) -> HTMLResponse:
    path = _FRONTEND / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Frontend file missing: {path}")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/", response_class=RedirectResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui")


for route, page in [
    ("/ui", "index.html"),
    ("/ui/items", "items.html"),
    ("/ui/search", "search.html"),
    ("/ui/status", "status.html"),
    ("/ui/failures", "failures.html"),
]:
    app.add_api_route(
        route, (lambda p=page: _html(p)), methods=["GET"], response_class=HTMLResponse
    )


@app.get("/api/frontend-fragments")
def frontend_fragments() -> list[dict]:
    config = load_config()
    plugins = discover_plugins(config, tool_root=_TOOL_ROOT)
    commands = discover_commands(plugins, tool_root=_TOOL_ROOT)
    return [
        {"source": p.name, "kind": "plugin", "js": p.frontend_js}
        for p in plugins.values()
        if p.frontend_js
    ] + [
        {"source": c.name, "kind": "command", "js": c.frontend_js}
        for c in commands.values()
        if c.frontend_js
    ]


@app.get("/api/failures")
def list_failures(source: str | None = Query(None)) -> list[dict]:
    from storage.sqlite_store import SQLiteStore

    config = load_config()
    store = SQLiteStore(config.get("db_path"))
    return store.list_failures(source)


@app.post("/api/failures/{source_plugin}/{source_id}/resync")
def resync_failure(source_plugin: str, source_id: str) -> dict:
    from urllib.parse import unquote
    from core.embedder import Embedder
    from core.handle import make_handle
    from core.sync_engine import chunk_by_sections
    from plugins.base import ItemMeta
    from storage.sqlite_store import SQLiteStore

    config = load_config()
    store = SQLiteStore(config.get("db_path"))

    failure = store.list_failures(source_plugin)
    failure = [f for f in failure if f["source_id"] == source_id]
    if not failure:
        raise HTTPException(status_code=404, detail="Failure not found")
    failure = failure[0]
    vault_path = failure.get("vault_path")

    plugins = discover_plugins(config, tool_root=_TOOL_ROOT)
    if source_plugin not in plugins:
        raise HTTPException(
            status_code=400, detail=f"Unknown source plugin: {source_plugin}"
        )

    plugin_manifest = plugins[source_plugin]
    plugin_instance = plugin_manifest.source_plugin_class(config)

    item_meta = ItemMeta(
        source_id=source_id, metadata={"vault_path": vault_path} if vault_path else None
    )

    try:
        document = plugin_instance.fetch(item_meta)
        document.handle = make_handle(
            document.source_plugin, document.source_id, document.title
        )
        embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))

        content_hash = embedder.hash_text(document.raw_text)
        store.upsert_document(document, content_hash)

        texts = chunk_by_sections(document)
        embedded = embedder.embed_texts(texts)
        from core.models import Chunk

        chunks = [
            Chunk(
                source_plugin=document.source_plugin,
                source_id=document.source_id,
                chunk_index=ix,
                content=texts[ix],
                content_hash=content_hash,
                embedding=vector,
            )
            for ix, (content_hash, vector) in enumerate(embedded)
        ]
        store.replace_chunks(document.source_plugin, document.source_id, chunks)
        store.clear_failure(source_plugin, source_id)

        return {"success": True}
    except Exception as exc:
        from datetime import datetime

        error_type = "transient"
        if hasattr(exc, "permanent"):
            error_type = "permanent" if exc.permanent else "transient"
        store.record_failure(source_plugin, source_id, str(exc), error_type, vault_path)
        return {"success": False, "error": str(exc)}


def _load() -> None:
    config = load_config()
    plugins = discover_plugins(config, tool_root=_TOOL_ROOT)
    commands = discover_commands(plugins, tool_root=_TOOL_ROOT)
    for manifest in list(plugins.values()) + list(commands.values()):
        if manifest.api_router:
            app.include_router(manifest.api_router)


_load()
