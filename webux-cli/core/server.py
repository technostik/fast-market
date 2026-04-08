from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

from common import structlog
from common.core.registry import discover_plugins
from plugins.base import PluginManifest

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
.webux-shell { margin: 18px; color: var(--text); }
body { background: var(--bg); color: var(--text); margin: 0; }
"""


def _build_nav(plugins: dict[str, PluginManifest], active: str | None = None) -> str:
    links = []
    for plugin in plugins.values():
        klass = "active" if plugin.name == active else ""
        links.append(
            f'<a class="{klass}" href="/{plugin.name}">{plugin.tab_icon} {plugin.tab_label}</a>'
        )
    return f"<nav class=\"webux-nav\">{''.join(links)}</nav>"


def _inject_nav(plugin_html: str, nav_html: str) -> str:
    style_tag = f"<style>{_NAV_CSS}</style>"
    if "</head>" in plugin_html:
        plugin_html = plugin_html.replace("</head>", f"{style_tag}</head>", 1)
    else:
        plugin_html = style_tag + plugin_html

    if "<body" in plugin_html:
        body_start = plugin_html.find(">", plugin_html.find("<body")
        )
        if body_start != -1:
            return plugin_html[: body_start + 1] + nav_html + plugin_html[body_start + 1 :]

    return nav_html + plugin_html


def build_app(
    config: dict,
    plugins: dict[str, PluginManifest] | None = None,
    tool_root: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="webux-agent")

    manifests = plugins
    if manifests is None:
        if tool_root is None:
            raise RuntimeError("tool_root is required when plugins are not passed")
        manifests = discover_plugins(config, tool_root=tool_root)

    logger.info("plugins_discovered", count=len(manifests), names=list(manifests.keys()))

    for plugin in manifests.values():
        app.include_router(plugin.api_router, prefix=f"/api/{plugin.name}")

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
            f"<html><head><style>{_NAV_CSS}</style></head><body>{nav}"
            f'<main class="webux-shell"><h1>webux</h1><ul>{links}</ul></main></body></html>'
        )
        return HTMLResponse(html)

    for plugin in manifests.values():

        def _make_page_handler(plugin_manifest: PluginManifest):
            def _render_page() -> HTMLResponse:
                nav = _build_nav(manifests, active=plugin_manifest.name)
                return HTMLResponse(_inject_nav(plugin_manifest.frontend_html, nav))

            return _render_page

        app.add_api_route(
            f"/{plugin.name}",
            _make_page_handler(plugin),
            methods=["GET"],
            response_class=HTMLResponse,
        )

    return app
