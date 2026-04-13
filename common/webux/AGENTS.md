# common/webux

## Purpose
Shared contract and discovery mechanism for webux hub plugins.
Any fast-market package can contribute tabs to the webux server
by declaring a `fast_market.webux_plugins` entry point.

## Files
- `base.py` — WebuxPluginManifest dataclass (the contract)
- `registry.py` — discover_webux_plugins() via importlib.metadata entry points

## Entry Point Convention
Each contributing package declares in its pyproject.toml:

```toml
[project.entry-points."fast_market.webux_plugins"]
my_plugin_name = "my_package.webux.my_plugin.register:register"
```

The value must point to a callable: `register(config: dict) -> WebuxPluginManifest`.

## Plugin Directory Convention
Webux plugins inside a CLI tool live under:
  `{cli-root}/webux/{plugin_name}/register.py`

Multiple plugins from the same CLI are separate subdirectories:
  `{cli-root}/webux/corpus_search/register.py`
  `{cli-root}/webux/corpus_status/register.py`

## Lazy Loading
Plugins with `lazy=True` (the default) are not imported at hub startup.
Their router and HTML are loaded on first request. This means:
- Hub starts instantly regardless of how many plugins are installed
- A broken plugin does not prevent other tabs from working
- Plugins can import heavy dependencies (ML models, DB connections) safely

## Do's
- Always set lazy=True unless you have a specific reason not to
- Keep register() fast — defer heavy imports inside router handlers
- Use /api/{name}/ prefix for all API routes (the hub mounts them there)
- Test your plugin independently before wiring the entry point

## Don'ts
- Never import heavy dependencies at module level in register.py
- Never use names that conflict with existing plugins (hub raises on duplicates)
- Never include nav markup in frontend_html (hub injects it)
- Never hardcode the hub's port or base URL in your plugin


## Monorepo Fallback Discovery
- Primary discovery uses entry points.
- In local development, if no entry points are installed, registry falls back to scanning `*-cli/webux/*/register.py` in the repository root.
- This keeps `webux serve` working without reinstalling packages on each edit.
