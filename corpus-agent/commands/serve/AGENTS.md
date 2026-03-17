# commands/serve/

Implements the `corpus serve` CLI command.

## Extension points

This command is a thin wrapper over uvicorn startup and shared logging setup.

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
