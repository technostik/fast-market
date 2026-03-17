# commands/search/

Implements the `corpus search` CLI command and the GET /search API endpoint.

## Extension points

Plugins contribute additional filter options via `plugin_manifest.cli_options["search"]`.
The command callback passes all kwargs to `make_filters()` which maps them to
SearchFilters fields. To add a new filter:
1. Add a click.Option to your plugin's `cli_options["search"]`
2. Add the corresponding field to SearchFilters in storage/sqlite_store.py

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
