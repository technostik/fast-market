# monitor-cli/webux

Webux UI plugins contributed by monitor-cli to the fast-market webux hub.

## Plugins

### monitor/
Tab providing monitor logs and status UI.
Wraps existing `core.storage.MonitorStorage` APIs and keeps register() lightweight.

## Do's
- Import `MonitorStorage` inside handler functions, not at module level
- Reuse core storage query methods for logs/status/filters
- Keep plugin lazy and side-effect free

## Don'ts
- Don't duplicate storage logic from `core/storage.py`
- Don't perform heavy startup work in register()
