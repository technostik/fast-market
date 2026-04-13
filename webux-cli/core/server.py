from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from common import structlog
from common.webux.base import WebuxPluginManifest

logger = structlog.get_logger(__name__)


_NAV_CSS = """
:root {
  --bg: #1a1a2e;
  --bg-secondary: #16213e;
  --text: #eee;
  --text-dim: #888;
  --accent: #0f3460;
  --success: #4ade80;
  --error: #f87171;
  --warning: #fbbf24;
  --border: #333;
}
.webux-nav {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 999;
}
.webux-nav a {
  color: var(--text-dim);
  text-decoration: none;
  padding: 8px 12px;
  border-radius: 6px;
  background: transparent;
}
.webux-nav a:hover { color: var(--text); background: #1d2a4a; }
.webux-nav a.active { color: var(--text); background: var(--accent); }
.webux-nav .exit-btn {
  margin-left: auto;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--error);
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
}
.webux-nav .exit-btn:hover { background: #4a1d2a; color: #fff; }
.webux-shell { margin: 18px; color: var(--text); }
body { background: var(--bg); color: var(--text); margin: 0; }
"""

_WEBUX_EXIT_SCRIPT = """
<script>
async function webuxExit() {
  try {
    await fetch('/api/system/exit', { method: 'POST' });
  } catch (_) {
    // server may stop before response resolves
  }

  try {
    window.close();
  } catch (_) {
    // ignore
  }

  setTimeout(() => {
    window.location.href = 'about:blank';
  }, 200);
}
</script>
"""


def _build_nav(plugins: dict[str, WebuxPluginManifest], active: str | None = None) -> str:
    links = []
    for plugin in plugins.values():
        klass = "active" if plugin.name == active else ""
        links.append(
            f'<a class="{klass}" href="/{plugin.name}">{plugin.tab_icon} {plugin.tab_label}</a>'
        )
    links.append('<button class="exit-btn" onclick="webuxExit()">⏻ Exit</button>')
    return f"<nav class=\"webux-nav\">{''.join(links)}</nav>"


def _inject_nav(plugin_html: str, nav_html: str) -> str:
    style_tag = f"<style>{_NAV_CSS}</style>"
    script_tag = _WEBUX_EXIT_SCRIPT
    if "</head>" in plugin_html:
        plugin_html = plugin_html.replace(
            "</head>",
            f"{style_tag}{script_tag}</head>",
            1,
        )
    else:
        plugin_html = style_tag + script_tag + plugin_html

    if "<body" in plugin_html:
        body_start = plugin_html.find(">", plugin_html.find("<body"))
        if body_start != -1:
            return plugin_html[: body_start + 1] + nav_html + plugin_html[body_start + 1 :]

    return nav_html + plugin_html


def _mount_plugin_router(
    app: FastAPI,
    plugin: WebuxPluginManifest,
    mounted: set[str],
) -> None:
    if plugin.name in mounted:
        return
    if plugin.api_router is not None:
        app.include_router(plugin.api_router, prefix=f"/api/{plugin.name}")
    mounted.add(plugin.name)




def _make_page_handler(
    app: FastAPI,
    manifests: dict[str, WebuxPluginManifest],
    plugin: WebuxPluginManifest,
    mounted: set[str],
):
    def _render_page() -> HTMLResponse:
        if plugin.lazy and plugin.name not in mounted:
            _mount_plugin_router(app, plugin, mounted)
            logger.info("webux_plugin_lazy_mounted", name=plugin.name)
        nav = _build_nav(manifests, active=plugin.name)
        return HTMLResponse(_inject_nav(plugin.frontend_html, nav))

    return _render_page


def build_app(
    config: dict,
    plugins: dict[str, WebuxPluginManifest],
    shutdown_callback: Callable[[], None] | None = None,
) -> FastAPI:
    del config
    app = FastAPI(title="webux-agent")
    manifests = plugins

    logger.info("plugins_discovered", count=len(manifests), names=list(manifests.keys()))

    mounted_routers: set[str] = set()
    for plugin in manifests.values():
        if not plugin.lazy:
            _mount_plugin_router(app, plugin, mounted_routers)

    @app.middleware("http")
    async def lazy_api_mount(request: Request, call_next):
        path = request.url.path
        for plugin in manifests.values():
            if plugin.lazy and plugin.name not in mounted_routers:
                prefix = f"/api/{plugin.name}"
                if path == prefix or path.startswith(f"{prefix}/"):
                    _mount_plugin_router(app, plugin, mounted_routers)
                    logger.info("webux_plugin_lazy_mounted", name=plugin.name)
                    break
        return await call_next(request)

    @app.get("/")
    def root() -> RedirectResponse:
        first = next(iter(manifests.values()), None)
        if first is None:
            return RedirectResponse(url="/shell")
        return RedirectResponse(url=f"/{first.name}")

    @app.get("/shell", response_class=HTMLResponse)
    def shell_page() -> HTMLResponse:
        nav = _build_nav(manifests, active=None)
        links = "".join(
            [
                f'<li><a href="/{p.name}">{p.tab_icon} {p.tab_label}</a></li>'
                for p in manifests.values()
            ]
        )
        html = (
            f"<html><head><style>{_NAV_CSS}</style>{_WEBUX_EXIT_SCRIPT}</head><body>{nav}"
            f'<main class="webux-shell"><h1>webux</h1><ul>{links}</ul></main></body></html>'
        )
        return HTMLResponse(html)

    for plugin in manifests.values():
        app.add_api_route(
            f"/{plugin.name}",
            _make_page_handler(app, manifests, plugin, mounted_routers),
            methods=["GET"],
            response_class=HTMLResponse,
        )

    @app.post("/api/system/exit")
    def exit_server() -> dict[str, bool]:
        logger.info("server_exit_requested")
        if shutdown_callback:
            shutdown_callback()
        return {"ok": True}

    return app
