# commands/setconfig/

Implements the `corpus setconfig` CLI command.

## Extension points

This command is interactive and edits `config.yaml` in place.
Keep prompts explicit and preserve backward-compatible config keys.

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery.
