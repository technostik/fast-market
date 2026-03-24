# commands/reindex/

Implements the `corpus reindex` CLI command and the POST /reindex API endpoint.

## Extension points

The `--source` choices are built dynamically from discovered plugin manifests.

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
