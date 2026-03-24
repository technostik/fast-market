# commands/setup/

Implements the `corpus setup` CLI command.

## Extension points

This command wraps setup wizard invocation and shared logging setup.

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
