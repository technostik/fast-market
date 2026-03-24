# commands/sync/

Implements the `corpus sync` CLI command and the POST /sync API endpoint.

## Extension points

The `--source` choices are built dynamically from discovered plugin manifests.
Plugin-specific options may be injected via `plugin_manifest.cli_options["sync"]`.

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
