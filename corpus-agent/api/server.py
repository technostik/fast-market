from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from core.config import load_config
from core.registry import discover_commands, discover_plugins

app = FastAPI(title="corpus-agent")
_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def _html(name: str) -> HTMLResponse:
    path = _FRONTEND / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Frontend file missing: {path}")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/", response_class=RedirectResponse)
def root() -> RedirectResponse: return RedirectResponse(url="/ui")


for route, page in [("/ui", "index.html"), ("/ui/items", "items.html"), ("/ui/search", "search.html"), ("/ui/status", "status.html")]:
    app.add_api_route(route, (lambda p=page: _html(p)), methods=["GET"], response_class=HTMLResponse)


@app.get("/api/frontend-fragments")
def frontend_fragments() -> list[dict]:
    config = load_config()
    plugins = discover_plugins(config)
    commands = discover_commands(plugins)
    return ([{"source": p.name, "kind": "plugin", "js": p.frontend_js} for p in plugins.values() if p.frontend_js] +
            [{"source": c.name, "kind": "command", "js": c.frontend_js} for c in commands.values() if c.frontend_js])


def _load() -> None:
    config = load_config()
    plugins = discover_plugins(config)
    commands = discover_commands(plugins)
    for manifest in list(plugins.values()) + list(commands.values()):
        if manifest.api_router:
            app.include_router(manifest.api_router)


_load()
