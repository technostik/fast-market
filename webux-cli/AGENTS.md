# webux-agent/

## 🎯 Purpose
Provides a modular web UI server for fast-market where each plugin contributes one API namespace and one top-level tab page.

## 🏗️ Essential Components
- `webux_entry/__init__.py` — package entry point exporting CLI `main`
- `cli/main.py` — CLI bootstrap and plugin/command auto-discovery
- `core/server.py` — FastAPI app factory, plugin router mounting, shared nav injection
- `core/security.py` — shared path containment checker
- `plugins/base.py` — `PluginManifest` contract for tab + API contribution
- `commands/base.py` — `CommandManifest` for discoverable CLI commands
- `commands/serve/register.py` — `webux serve` server command
- `plugins/*/register.py` — plugin manifests discovered at runtime

## 📦 Plugin Manifest Contract
Each plugin `register(config)` must return `PluginManifest` with:
- `name` — tab id and API prefix segment
- `tab_label` — user-visible tab text
- `tab_icon` — emoji/single-char icon shown in nav
- `api_router` — mounted under `/api/{name}/`
- `frontend_html` — standalone plugin page HTML

## 🌐 API Conventions
- All plugin APIs live under `/api/{plugin_name}/...`
- Plugin UI pages live under `/{plugin_name}`
- Root (`/`) redirects to first discovered plugin tab
- Nav bar is generated once in `core/server.py` and injected into every plugin page

## 🔒 Security Rules
- Any filesystem access must validate containment with `core.security._assert_path_safe(path, roots)`
- `Path.resolve()` must be used before containment checks
- Reject out-of-root paths with HTTP 403
- Avoid symlink traversal when building directory trees

## ✅ Do's
- Keep plugins independent and discoverable (`plugins/*/register.py` only)
- Use `common.core.registry.discover_plugins(..., tool_root=...)`
- Fail loudly when plugin registration contract is invalid
- Use `common.structlog` for server/plugin/API/subprocess logging
- Keep API payloads backward compatible where feasible

## ❌ Don'ts
- Don’t hardcode plugin names in `core/server.py`
- Don’t bypass `_assert_path_safe` for path-bearing endpoints
- Don’t duplicate nav markup across plugin HTML files
- Don’t mount plugin routers outside `/api/{name}`
- Don’t silently ignore malformed plugin registration

## 🧩 Extension Points (Add a New Tab Plugin)
1. Create `plugins/<new_plugin>/` with `__init__.py`, `plugin.py`, `register.py`.
2. Build a FastAPI router in `plugin.py`.
3. Return a `PluginManifest` in `register.py`.
4. Ensure endpoints follow `/api/{name}/...` semantics.
5. Provide full `frontend_html` (server injects shared nav automatically).
6. Restart `webux serve` and verify tab appears automatically.
