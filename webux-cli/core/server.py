from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from common import structlog
from common.webux.base import WebuxPluginManifest
from common.webux.theme import (
    DEFAULT_THEME,
    THEME_NAMES,
    codemirror_theme,
    render_all_themes_css,
    render_root_css,
    resolve_theme,
)

logger = structlog.get_logger(__name__)


# Base font shared by the hub chrome and every plugin page body.
# The hub stylesheet is injected AFTER each plugin's own <style>, so on equal
# specificity these hub rules win — plugin `body` fonts cannot leak into the nav.
_WEBUX_BASE_FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif"
)

_NAV_LAYOUT = (
    """
.webux-nav {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 999;
  align-items: center;
  font-family: __WEBUX_BASE_FONT__;
  font-size: 14px;
  font-weight: 400;
  line-height: 1.4;
}
/* Isolate the nav from plugin resets (e.g. `* { box-sizing }`) and generic
   element rules (e.g. `button { font-weight: 600 }`, `select { width: 100% }`). */
.webux-nav, .webux-nav *, .webux-nav *::before, .webux-nav *::after {
  box-sizing: border-box;
  margin: 0;
}
.webux-nav a {
  color: var(--text-dim);
  text-decoration: none;
  padding: 8px 12px;
  border-radius: 6px;
  background: transparent;
  font: inherit;
  white-space: nowrap;
  flex-shrink: 0;
  border: none;
}
.webux-nav a:hover { color: var(--text); background: var(--surface); }
.webux-nav a.active { color: var(--text); background: var(--accent); }
.webux-nav .theme-select {
  margin-left: auto;
  padding: 8px 10px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
  width: auto;
  max-width: 170px;
  flex-shrink: 0;
}
.webux-nav .exit-btn {
  margin-left: 8px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--error);
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
  width: auto;
  flex-shrink: 0;
  white-space: nowrap;
}
.webux-nav .exit-btn:hover { background: var(--surface); color: var(--text); }
.webux-shell { margin: 18px; color: var(--text); }
/* Unified base font for every tab. Injected after plugin styles, so this wins
   over per-plugin `body` font rules (same specificity, later in cascade). */
body {
  background: var(--bg);
  color: var(--text);
  margin: 0;
  padding: 0;
  font-family: __WEBUX_BASE_FONT__;
  font-size: 14px;
  line-height: 1.4;
}
/* Page-content wrapper for tabs that need the legacy 16px page padding.
   Body padding stays 0 so the tab bar is full-bleed and identical on every tab. */
.webux-page { padding: 16px; }
""".replace("__WEBUX_BASE_FONT__", _WEBUX_BASE_FONT)
)

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

_WEBUX_THEME_BOOT_SCRIPT = """
<script>
/* Apply persisted per-browser theme before first paint (avoids FOUC). */
(function () {
  try {
    var t = localStorage.getItem('webux-theme');
    if (t === 'dark' || t === 'light' || t === 'blue') {
      document.documentElement.setAttribute('data-theme', t);
    }
  } catch (_) { /* storage unavailable */ }
})();
</script>
"""

_WEBUX_THEME_SCRIPT = """
<script>
var WEBUX_THEMES = ['dark', 'light', 'blue'];
var WEBUX_CODEMIRROR = { dark: 'dracula', light: 'default', blue: 'dracula' };
function webuxGetTheme() {
  var t = null;
  try { t = localStorage.getItem('webux-theme'); } catch (_) {}
  if (WEBUX_THEMES.indexOf(t) === -1) {
    t = document.documentElement.getAttribute('data-theme') || 'dark';
  }
  if (WEBUX_THEMES.indexOf(t) === -1) t = 'dark';
  return t;
}
function webuxApplyEditorTheme(theme) {
  var cmTheme = WEBUX_CODEMIRROR[theme] || 'dracula';
  try {
    if (window.editor && window.editor.setOption) {
      window.editor.setOption('theme', cmTheme);
    }
  } catch (_) {}
  try {
    document.querySelectorAll('.CodeMirror').forEach(function (el) {
      var cm = el.CodeMirror;
      if (cm && cm.setOption) cm.setOption('theme', cmTheme);
    });
  } catch (_) {}
  /* CodeMirror 5 "default" theme lives in the base stylesheet; the dracula
     file only overrides. So light = disable dracula sheet, dark/blue = enable. */
  try {
    document.querySelectorAll('link[data-cm-theme="dracula"]').forEach(function (link) {
      link.disabled = (cmTheme === 'default');
    });
  } catch (_) {}
}
function webuxSetTheme(theme, persist) {
  if (WEBUX_THEMES.indexOf(theme) === -1) return;
  document.documentElement.setAttribute('data-theme', theme);
  if (persist !== false) {
    try { localStorage.setItem('webux-theme', theme); } catch (_) {}
    try {
      fetch('/api/system/theme', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme: theme }),
      }).catch(function () {});
    } catch (_) {}
  }
  var sel = document.getElementById('webux-theme');
  if (sel && sel.value !== theme) sel.value = theme;
  webuxApplyEditorTheme(theme);
  try { window.dispatchEvent(new CustomEvent('webux-theme-change', { detail: { theme: theme } })); } catch (_) {}
}
document.addEventListener('DOMContentLoaded', function () {
  var current = webuxGetTheme();
  document.documentElement.setAttribute('data-theme', current);
  var sel = document.getElementById('webux-theme');
  if (sel) {
    sel.value = current;
    sel.addEventListener('change', function () { webuxSetTheme(sel.value); });
  }
  webuxApplyEditorTheme(current);
});
</script>
"""

_PROMPT_INFO_CSS = """
.prompt-info { position: relative; cursor: help; color: var(--text); font-weight: 400; margin-left: 6px; }
.prompt-info:hover::after {
  content: attr(data-content);
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 4px;
  display: block;
  width: min(640px, 85vw);
  max-height: 340px;
  overflow: auto;
  white-space: pre-wrap;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 8px;
  font-size: 11px;
  font-family: monospace;
  color: var(--text);
  z-index: 999;
  box-shadow: 0 4px 16px rgba(0,0,0,.4);
}
"""

_PROMPT_INFO_SCRIPT = """
<script>
// Wire an (i) info bubble to a prompt-select: on hover it shows the currently
// selected prompt's content (fetched from /api/system/prompt-content).
function setupPromptInfo(selectId, infoId) {
  const sel = document.getElementById(selectId);
  const info = document.getElementById(infoId);
  if (!sel || !info) return;
  if (info.dataset.bound) return;
  info.dataset.bound = '1';
  const load = async () => {
    const name = sel.value;
    if (!name) { info.dataset.content = '(no prompt selected)'; return; }
    try {
      const r = await fetch('/api/system/prompt-content?name=' + encodeURIComponent(name));
      const d = await r.json();
      info.dataset.content = d.content || d.error || '(empty)';
    } catch (e) {
      info.dataset.content = '(failed to load)';
    }
  };
  info.addEventListener('mouseenter', load);
  sel.addEventListener('change', () => { info.dataset.content = ''; });
}
</script>
"""


def _build_nav(
    plugins: dict[str, WebuxPluginManifest],
    active: str | None = None,
    current_theme: str = DEFAULT_THEME,
) -> str:
    links = []
    for plugin in plugins.values():
        klass = "active" if plugin.name == active else ""
        links.append(
            f'<a class="{klass}" href="/{plugin.name}">{plugin.tab_icon} {plugin.tab_label}</a>'
        )
    options = "".join(
        f'<option value="{name}"{" selected" if name == current_theme else ""}>'
        f'{"🌙" if name == "dark" else "☀️" if name == "light" else "🔵"} {name}'
        f"</option>"
        for name in THEME_NAMES
    )
    links.append(
        f'<select id="webux-theme" class="theme-select" title="Theme">'
        f"{options}</select>"
    )
    links.append('<button class="exit-btn" onclick="webuxExit()">⏻ Exit</button>')
    return f"<nav class=\"webux-nav\">{''.join(links)}</nav>"


def _inject_nav(
    plugin_html: str, nav_html: str, default_theme: str = DEFAULT_THEME
) -> str:
    if default_theme not in THEME_NAMES:
        default_theme = DEFAULT_THEME
    theme_css = render_all_themes_css()
    style_tag = f"<style>{theme_css}{_NAV_LAYOUT}{_PROMPT_INFO_CSS}</style>"
    # Boot script must run ASAP (in <head>) to avoid a flash of the wrong theme.
    head_tags = _WEBUX_THEME_BOOT_SCRIPT + style_tag
    script_tag = _WEBUX_EXIT_SCRIPT + _WEBUX_THEME_SCRIPT + _PROMPT_INFO_SCRIPT
    if "</head>" in plugin_html:
        plugin_html = plugin_html.replace(
            "</head>",
            f"{head_tags}{script_tag}</head>",
            1,
        )
    else:
        plugin_html = head_tags + script_tag + plugin_html

    # Ensure <html> carries the server default so first paint is correct
    # even when localStorage is empty. The boot script overrides per-browser.
    if "<html" in plugin_html:
        idx = plugin_html.find("<html")
        end = plugin_html.find(">", idx)
        if end != -1:
            tag = plugin_html[idx : end + 1]
            if "data-theme" not in tag:
                plugin_html = (
                    plugin_html[:end]
                    + f' data-theme="{default_theme}"'
                    + plugin_html[end:]
                )

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
        for route in app.router.routes:
            if not hasattr(route, "path"):
                include_context = getattr(route, "include_context", None)
                original_router = getattr(route, "original_router", None)
                first_path = ""
                if original_router is not None and getattr(original_router, "routes", None):
                    first_path = getattr(original_router.routes[0], "path", "")
                route.path = f"{getattr(include_context, 'prefix', '')}{first_path}"
    mounted.add(plugin.name)


def _make_page_handler(
    app: FastAPI,
    manifests: dict[str, WebuxPluginManifest],
    plugin: WebuxPluginManifest,
    mounted: set[str],
):
    def _render_page(request: Request) -> HTMLResponse:
        if plugin.lazy and plugin.name not in mounted:
            _mount_plugin_router(app, plugin, mounted)
            logger.info("webux_plugin_lazy_mounted", name=plugin.name)
        theme_q = request.query_params.get("theme", "")
        default_theme = getattr(app.state, "webux_theme", DEFAULT_THEME)
        if theme_q in THEME_NAMES:
            default_theme = theme_q
        nav = _build_nav(manifests, active=plugin.name, current_theme=default_theme)
        return HTMLResponse(
            _inject_nav(plugin.frontend_html, nav, default_theme),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    return _render_page


def build_app(
    config: dict,
    plugins: dict[str, WebuxPluginManifest],
    shutdown_callback: Callable[[], None] | None = None,
) -> FastAPI:
    initial_theme = resolve_theme(config if isinstance(config, dict) else {})
    app = FastAPI(title="webux-agent")
    app.state.webux_theme = initial_theme
    manifests = plugins

    logger.info(
        "plugins_discovered",
        count=len(manifests),
        names=list(manifests.keys()),
        theme=initial_theme,
    )

    mounted_routers: set[str] = set()
    for plugin in manifests.values():
        if not plugin.lazy:
            _mount_plugin_router(app, plugin, mounted_routers)

    @app.middleware("http")
    async def lazy_api_mount(request: Request, call_next):
        path = request.url.path
        mounted_this_request = False

        for plugin in manifests.values():
            if plugin.lazy and plugin.name not in mounted_routers:
                prefix = f"/api/{plugin.name}"
                if path == prefix or path.startswith(f"{prefix}/"):
                    _mount_plugin_router(app, plugin, mounted_routers)
                    logger.info("webux_plugin_lazy_mounted", name=plugin.name)
                    mounted_this_request = True

        if path.startswith("/api/") and not mounted_this_request and not path.startswith("/api/system/"):
            mounted_names = {p.name for p in manifests.values() if p.name in mounted_routers}
            matched = any(path.startswith(f"/api/{n}/") or path == f"/api/{n}" for n in mounted_names)
            if not matched:
                logger.warning(
                    "webux_no_matching_plugin",
                    path=path,
                    mounted=list(mounted_names),
                    known=list(manifests.keys()),
                )

        return await call_next(request)

    @app.get("/")
    def root() -> RedirectResponse:
        first = next(iter(manifests.values()), None)
        if first is None:
            return RedirectResponse(url="/shell")
        return RedirectResponse(url=f"/{first.name}")

    @app.get("/shell", response_class=HTMLResponse)
    def shell_page(request: Request) -> HTMLResponse:
        theme_q = request.query_params.get("theme", "")
        default_theme = getattr(app.state, "webux_theme", DEFAULT_THEME)
        if theme_q in THEME_NAMES:
            default_theme = theme_q
        nav = _build_nav(manifests, active=None, current_theme=default_theme)
        links = "".join(
            [
                f'<li><a href="/{p.name}">{p.tab_icon} {p.tab_label}</a></li>'
                for p in manifests.values()
            ]
        )
        theme_css = render_all_themes_css()
        html = (
            f'<html data-theme="{default_theme}"><head><style>{theme_css}{_NAV_LAYOUT}</style>'
            f"{_WEBUX_THEME_BOOT_SCRIPT}{_WEBUX_EXIT_SCRIPT}{_WEBUX_THEME_SCRIPT}</head>"
            f"<body>{nav}"
            f'<main class="webux-shell"><h1>webux</h1><ul>{links}</ul></main></body></html>'
        )
        return HTMLResponse(html)

    @app.get("/theme.css", response_class=PlainTextResponse)
    def theme_css() -> PlainTextResponse:
        return PlainTextResponse(
            render_all_themes_css(),
            media_type="text/css",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    @app.get("/api/system/theme")
    def get_theme() -> dict:
        current = getattr(app.state, "webux_theme", DEFAULT_THEME)
        return {
            "theme": current,
            "available": list(THEME_NAMES),
            "codemirror": {name: codemirror_theme(name) for name in THEME_NAMES},
        }

    @app.post("/api/system/theme")
    def set_theme(payload: dict) -> dict:
        name = (payload or {}).get("theme", "")
        if name not in THEME_NAMES:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail=f"Unknown theme '{name}'. Available: {', '.join(THEME_NAMES)}",
            )
        app.state.webux_theme = name
        logger.info("webux_theme_changed", theme=name)
        return {"ok": True, "theme": name}

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

    @app.get("/api/system/prompt-content")
    def system_prompt_content(name: str = ""):
        if not name:
            return {"name": name, "content": "", "error": "missing name"}
        import shutil
        import subprocess

        pr = shutil.which("prompt") or "prompt"
        try:
            proc = subprocess.run(
                [pr, "get", name, "--content"],
                capture_output=True, text=True, check=False,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return {"name": name, "content": "", "error": f"prompt error: {exc}"}
        if proc.returncode != 0:
            return {
                "name": name,
                "content": "",
                "error": (proc.stderr or proc.stdout or "prompt get failed").strip(),
            }
        return {"name": name, "content": proc.stdout.strip()}

    # Re-export for tests that import render helpers from core.server.
    app.state.render_root_css = render_root_css  # type: ignore[attr-defined]

    return app
