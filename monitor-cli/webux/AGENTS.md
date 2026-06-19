# monitor-cli/webux

## 🎯 Purpose
Contributes a **Monitor** tab to the `webux serve` hub, exposing monitor logs, running status, statistics, rerun, and diagnostics via a FastAPI router and inline HTML.

## 🏗️ Essential Components
- `monitor/register.py` — `register(config) -> WebuxPluginManifest`; defines the FastAPI `router` and inline `_HTML`; registered as `fast_market.webux_plugins` entry point `monitor`
- `monitor/register.py:_get_monitor_storage_class()` — dynamic import helper that isolates `core.storage` from the webux process's own `core.*` modules to prevent namespace collisions

## 📋 Core Responsibilities
- Serve trigger logs and run-error logs merged and sorted by time (`GET /api/monitor/logs`)
- Report status statistics and entity IDs (`GET /api/monitor/status`)
- Expose filter options (rule_ids, source_ids, action_ids) (`GET /api/monitor/filters`)
- Rerun a past trigger action (`POST /api/monitor/rerun/{trigger_log_id}`)
- Report running/idle state from `/tmp/fast-market-monitor.state.json` (`GET /api/monitor/running`)
- Relay wait/stop signals via sentinel files (`POST /api/monitor/wait`, `POST /api/monitor/stop`)
- Delegate diagnostics to `toolsetup diagnose -F json` via subprocess (`POST /api/monitor/diagnose`)

## 🔗 Dependencies & Integration
- Imports from: `common.core.paths` (`get_tool_data_dir`), `common.webux.base` (`WebuxPluginManifest`)
- Reads: `~/.local/share/fast-market/monitor/monitor.db` via `MonitorStorage` (dynamically imported)
- Reads: `/tmp/fast-market-monitor.state.json` for running status
- Writes: `/tmp/fast-market-monitor.wait`, `/tmp/fast-market-monitor.stop` as sentinel files
- Calls: `toolsetup diagnose -F json` via `subprocess` for diagnostics
- Registered in `monitor-cli/pyproject.toml` under `[project.entry-points."fast_market.webux_plugins"]`

## ✅ Do's
- Import `MonitorStorage` inside request handler functions via `_get_monitor_storage_class()` — not at module level
- Reuse `core.storage` query methods for all logs/status/filters — don't re-implement queries
- Keep `register()` side-effect-free and fast — all heavy work deferred to request handlers
- Use `lazy=True` on the manifest (default) so the tab loads on first browser visit

## ❌ Don'ts
- Don't duplicate storage query logic from `core/storage.py`
- Don't import `core.*` at module level — the webux process may have its own `core` module that would shadow this one
- Don't perform blocking I/O in `register()`

## ⚠️ Pitfalls
- **core.* namespace collision**: webux-cli and monitor-cli both have a `core/` package. `_get_monitor_storage_class()` saves, removes, and restores `sys.modules["core"]` entries around the import. If this helper is bypassed or broken, `MonitorStorage` will silently load the wrong module.
- **state file timezone**: `/tmp/fast-market-monitor.state.json` stores `started_at` as ISO without timezone; the handler treats naive datetimes as UTC. If the monitor writes naive and the webux process compares with `timezone.utc`, elapsed time is correct.
- **stale state file**: running status is considered stale if `elapsed_sec > 7200`; the endpoint returns `{"status": "idle", "stale": True}` in that case.

## 🧪 Tests
- Test files: `tests/test_webux_monitor_imports.py`
- Run with: `pytest tests/test_webux_monitor_imports.py -v` from `monitor-cli/`

## 🔍 Observability
- No structured logging in this module (thin wrapper)
- Monitor actions log to `monitor.db` trigger_logs table; query via `GET /api/monitor/logs`

## 🛠️ Extension Points
- Add new API routes directly to `router` in `monitor/register.py`
- Update `_HTML` string for frontend changes (self-contained inline HTML)
- To expose new storage queries, add methods to `core/storage.py` and call via `_get_monitor_storage_class()`

## 📚 Related Documentation
- See `../README.md` for monitor CLI reference and cron setup
- See `../AGENTS.md` for the full monitor system architecture
- See `webux-cli/AGENTS.md` for `WebuxPluginManifest` contract and tab plugin extension guide
