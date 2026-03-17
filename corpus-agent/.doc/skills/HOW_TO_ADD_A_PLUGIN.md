# How to add a new plugin

## Steps

1. Create `plugins/<name>/` with:
   - `__init__.py` (empty)
   - `plugin.py` — subclass `SourcePlugin`, implement `list_items()` and `fetch()`
   - `register.py` — implement `register(config) -> PluginManifest`
   - `AGENTS.md` — describe source, sync cursor, options

2. In `register.py`:
   ```python
   from plugins.base import PluginManifest
   from plugins.<name>.plugin import MyPlugin
   import click

   def register(config: dict) -> PluginManifest:
       return PluginManifest(
           name="<name>",
           source_plugin_class=MyPlugin,
           cli_options={
               "search": [
                   click.Option(["--my-filter"], type=int, default=None,
                                help="My plugin-specific filter."),
               ],
           },
       )
   ```

3. Add `"plugins.<name>"` to `[tool.setuptools] packages` in `pyproject.toml`.

4. Write tests:
   - Unit test for `plugin.py` in `tests/test_<name>.py`
   - Add CLI integration tests to `tests/test_cli.py`

## What happens automatically

The plugin is discovered by `core/registry.py` on next startup.
Its CLI options appear in the relevant commands' `--help`.
Its API router (if any) is included in the FastAPI app.
No changes to `cli/main.py`, `api/server.py`, or any other file.

## Note: --source option

Do NOT declare a `--source` option in your plugin. Commands build `--source`
dynamically from all registered plugin names.
