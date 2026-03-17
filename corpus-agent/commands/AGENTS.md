# commands/

Each subdirectory is a self-contained command module.

## Required structure per command directory

- `__init__.py` (empty)
- `register.py` — exports `register(plugin_manifests: dict) -> CommandManifest`
- `AGENTS.md` — describes what the command does and its extension points

## Rules

- Commands MUST NOT import plugin names directly (obsidian, youtube, etc.).
  They receive plugin_manifests and iterate generically.
- A command's base Click options are declared inside its own register.py.
  Plugin-specific options are injected by the registry at load time via
  `command.params.extend(plugin_manifest.cli_options.get(cmd_name, []))`.
- The --source option for commands that target a specific plugin (sync, reindex)
  is built dynamically: `list(plugin_manifests.keys()) + ["all"]`.
  No command hardcodes ["obsidian", "youtube"].
- Global options (--verbose, --format) live on the root Click group.
  Commands read them via ctx.obj — they must NOT re-declare them.
- Deleting a command directory removes it from CLI and API entirely.
  No other file needs to change.
- Use structlog, raise explicit exceptions. Follow KISS and DRY.
