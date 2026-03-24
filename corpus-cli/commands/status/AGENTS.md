# commands/status/

Implements the `corpus status` CLI command and listing API endpoints (`/sources`, `/items`).

## Extension points

Listing and filter behavior should align with `SearchFilters` in storage/sqlite_store.py.

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
