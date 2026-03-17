# commands/get/

Implements the `corpus get` CLI command and document lookup API endpoints.

## Extension points

This command reads indexed documents by handle or source identifiers.
Keep output formats stable (`meta`, `content`, `all`) when extending.

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
