# commands/setup/

Implements the `corpus setup` CLI group with subcommands for configuration and setup.

## Subcommands

- `corpus setup run` - Run the interactive setup wizard
- `corpus setup wizard` - Run the interactive wizard to edit config.yaml settings
- `corpus setup edit` - Open config.yaml in your default editor

## Extension points

Subcommands are auto-discovered from `subcommands/` directory.
Each subcommand must implement `register(plugin_manifests) -> click.Command`.

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery. Returns a Click group with subcommands.
