# webux-cli

## 🎯 Purpose
Modular web UI server for fast-market: a single `webux serve` process hosts multiple plugin tabs, each contributing one FastAPI router and one UI page.

## 🏗️ Essential Components
- `webux_entry/__init__.py` — package entry point, exports `main`
- `cli/main.py` — CLI bootstrap: discovers plugins and commands via `common.core.registry`
- `core/server.py` — FastAPI app factory: lazy-mounts plugin routers, injects shared nav into every plugin page
- `core/security.py` — `_assert_path_safe(path, roots)` path containment guard (HTTP 403 on violation)
- `commands/serve/register.py` — `webux serve` (uvicorn, --host, --port, --open, --restart)
- `commands/setup/register.py` — `webux setup show | reset | show-path`
- `webux/fileviewer/` — **Files** tab: browse/edit config, data, workdir files with CodeMirror
- `webux/yt_poster/` — **YT Poster** tab: batch-post YouTube comments/videos, regenerate replies
- `webux/skill_runner/` — **Plan Editor** tab: load `*.run.yaml` plans, edit skill/prompt files

## 📋 Core Responsibilities
- Serve a unified dark-themed web UI at `http://host:port/`
- Mount each plugin's FastAPI router under `/api/{plugin_name}/`
- Serve each plugin's page at `/{plugin_name}` with shared nav injected automatically
- Lazy-mount routers: defer `app.include_router()` until the first request to `/{name}` or `/api/{name}/...`
- Expose `POST /api/system/exit` for in-browser server shutdown

## 🔗 Dependencies & Integration
- Imports from: `common.webux.base` (`WebuxPluginManifest`), `common.webux.registry` (`discover_webux_plugins`), `common.core.registry`, `common.core.config`, `common.structlog`
- Plugins registered via `pyproject.toml` entry group `fast_market.webux_plugins`
- `yt_poster` calls `youtube batch-comment-post/batch-video-post` and `prompt batch-apply` via subprocess
- `yt_poster` calls `toolsetup workdir prev/last` for workdir navigation
- External deps: `fastapi`, `uvicorn`, `psutil` (port kill on `--restart`), `pyyaml`, `requests` (skill_runner URL load)

## 📦 WebuxPluginManifest Contract
Each `register(config: dict) -> WebuxPluginManifest` must provide:

| Field | Description |
|-------|-------------|
| `name` | Unique slug — tab id, URL path, API prefix |
| `tab_label` | Visible tab label |
| `tab_icon` | Emoji shown in nav |
| `api_router` | `APIRouter` mounted at `/api/{name}/` |
| `frontend_html` | Full HTML page (server injects nav CSS + JS + `<nav>` automatically) |
| `order` | Integer for tab ordering (lower = leftmost) |
| `lazy` | `True` by default — defers router mount to first request |

## 🌐 API Conventions
- Plugin APIs: `/api/{plugin_name}/...`
- Plugin UI pages: `/{plugin_name}`
- Root `/` redirects to first discovered plugin tab
- `/shell` fallback page lists all tabs
- `POST /api/system/exit` → graceful shutdown

## 🔒 Security Rules
- Every filesystem endpoint must call `_assert_path_safe(resolved_path, roots)` before read/write
- Use `Path.resolve()` before the safety check — never pass raw user input
- Reject out-of-root paths with HTTP 403
- Never traverse symlinks in directory trees (`_tree()` skips symlinks)

## ✅ Do's
- Discover plugins via entry points — never hardcode names in `core/server.py`
- Keep `register()` side-effect-free; defer heavy imports into request handlers
- Use `common.structlog` for all logging (structured, grep-friendly)
- Always create a `.bak` backup before overwriting files (both fileviewer and skill_runner do this)
- Fail loudly on malformed plugin registration — do not swallow errors at startup

## ❌ Don'ts
- Don't hardcode plugin names in `core/server.py`
- Don't bypass `_assert_path_safe` for any path-bearing endpoint
- Don't duplicate nav markup in plugin HTML — server injects it
- Don't mount plugin routers outside `/api/{name}/...`

## ⚠️ Pitfalls
- **--restart requires psutil**: `psutil` kills the process on the target port; if not installed the flag silently does nothing. Ensure `psutil` is in the dependencies.
- **lazy mount race**: the ASGI middleware mounts lazily; concurrent requests to an unmounted plugin may 404 on the first hit. Acceptable for single-user CLI use.
- **yt_poster subprocess path**: calls `youtube` and `prompt` CLIs — they must be in `PATH` and configured. Missing CLI → HTTP 500 with the subprocess error in the response.
- **workdir not configured**: `yt_poster` and `fileviewer` return HTTP 404 when `workdir` is absent from `~/.config/fast-market/common/config.yaml`. Run `toolsetup workdir init <path>` first.
- **plugin order**: `order` in `WebuxPluginManifest` controls tab position; lower numbers appear leftmost. Default ordering: fileviewer=30, skill_runner=20, yt_poster=40, monitor=20.

## 🧪 Tests
- Test files: `tests/`
- Run with: `pytest tests/ -v` from `webux-cli/`
- Key scenarios: `test_fileviewer_listing.py` (tree/file API), `test_server_lazy.py` (lazy mount), `test_yt_poster.py` (post/load API)

## 🔍 Observability
- Verbose logging: pass `--verbose` via CLI context; default level is `CRITICAL`
- Key log markers: `server_start`, `server_exit_requested`, `webux_plugin_lazy_mounted`, `webux_no_matching_plugin`, `yt_poster_load`, `yt_poster_post_start`, `yt_poster_post_done`, `fileviewer_tree`, `fileviewer_read_file`, `fileviewer_save_file`, `skill_runner_tree`, `skill_runner_read_file`

## 🛠️ Extension Points
- **Add a new tab plugin**:
  1. Create `webux/<name>/` with `__init__.py`, `plugin.py` (FastAPI `APIRouter`), `register.py` (returns `WebuxPluginManifest`)
  2. Add entry point in `pyproject.toml` under `[project.entry-points."fast_market.webux_plugins"]`
  3. Reinstall: `pip install -e .`
  4. Restart `webux serve` — tab appears automatically
- **Add CLI command**: create `commands/<name>/register.py`, implement `register(plugin_manifests) -> CommandManifest`
- **Add API routes to an existing plugin**: add `@router.get/post/put` handlers in `webux/<name>/plugin.py`

## 📚 Related Documentation
- See `README.md` for installation, serve options, and per-tab usage
- See `common/AGENTS.md` for shared infrastructure (structlog, config, webux base classes)
