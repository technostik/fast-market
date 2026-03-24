# commands/delete/

Implements the `corpus delete` CLI command and DELETE document API endpoint.

## Extension points

Deletion behavior should remain explicit and fail loudly when targets are missing.

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
