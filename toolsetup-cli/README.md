# toolsetup

Configure global settings and LLM providers for all fast-market CLI tools.

## Installation

```bash
pip install -e ./toolsetup-cli
```

## Interactive Setup Wizard

Run without arguments to launch the interactive configuration wizard:

```bash
toolsetup
```

Guides you through configuring LLM providers and setting a global default workdir.

## Configuration Files

| Config | Path |
|--------|------|
| Common (workdir) | `~/.config/fast-market/common/config.yaml` |
| LLM providers | `~/.config/fast-market/common/llm/config.yaml` |
| YouTube | `~/.config/fast-market/youtube/config.yaml` |
| Agent | `~/.config/fast-market/agent/config.yaml` |
| Completions | `~/.config/fast-market/completions/` |
| Data | `~/.local/share/fast-market/` |

## CLI Reference

### Global flags

```bash
# Show all config values
toolsetup --show

# Show all config file paths
toolsetup --show-path
```

### `toolsetup show`

Show config file contents. Default: show all.

```bash
toolsetup show
toolsetup show --llm
toolsetup show --workdir
toolsetup show --youtube
toolsetup show --agent
```

### `toolsetup path`

Show config file paths.

```bash
toolsetup path
toolsetup path --llm
toolsetup path --workdir
toolsetup path --youtube
toolsetup path --agent
```

### `toolsetup edit`

Open config files in `$EDITOR`. Default: open all.

```bash
toolsetup edit
toolsetup edit --llm
toolsetup edit --workdir
toolsetup edit --youtube
toolsetup edit --agent
```

### `toolsetup diagnose`

Run health checks on workdir, LLM connectivity, and YouTube API.

```bash
toolsetup diagnose
toolsetup diagnose --format json
toolsetup diagnose --provider anthropic       # Test a specific LLM provider (autocomplete from configured providers)
toolsetup diagnose -t llm -t workdir          # Run only specific tests (repeatable)
toolsetup diagnose -t llm --verbose           # Show raw LLM request/response
```

Both `--provider` and `--test` support shell autocomplete (Tab).

Available tests: `workdir`, `llm`, `youtube`, `groq_transcription`, `modal_connectivity`, `modal_groq_transcription`

---

### `toolsetup llm`

Manage LLM provider configuration.

```bash
# List configured providers
toolsetup llm list

# Add or reconfigure a provider (interactive)
toolsetup llm add anthropic
toolsetup llm add openai
toolsetup llm add openai-compatible
toolsetup llm add ollama

# Remove a provider
toolsetup llm remove openai

# Set default provider
toolsetup llm set-default anthropic
```

Available providers: `anthropic`, `openai`, `openai-compatible`, `ollama`

**API key env vars are stored, never the keys themselves.** After adding a provider, export the key:

```bash
export ANTHROPIC_API_KEY=your-key
```

---

### `toolsetup workdir`

Manage workdir subdirectories within a `workdir_root`. Supports history navigation and locking.

```bash
# Initialize workdir_root (one-time setup)
toolsetup workdir init /path/to/workdir-root

# Create a new workdir (uuid suffix, auto-locked)
toolsetup workdir new

# List workdirs (newest first)
toolsetup workdir list

# Show current workdir
toolsetup workdir show

# Navigate history
toolsetup workdir prev   # Go to previous (older) workdir
toolsetup workdir last   # Go to most recent workdir

# Lock / unlock current workdir
toolsetup workdir lock
toolsetup workdir unlock
toolsetup workdir islocked

# Release lock (or create new workdir with --bypass)
toolsetup workdir release
toolsetup workdir release --bypass   # Unlock + create new immediately

# Reset current workdir back to workdir_root
toolsetup workdir reset

# Delete all workdirs matching the configured prefix
toolsetup workdir clean
toolsetup workdir clean --force
```

### `toolsetup clean-workdir`

Clean files in the simple global `workdir` (not the multi-workdir hierarchy).

```bash
# Clean all non-hidden files in workdir (with confirmation)
toolsetup clean-workdir

# Skip confirmation
toolsetup clean-workdir --force

# Also remove subdirectories and hidden files
toolsetup clean-workdir --all
```

---

### `toolsetup reset`

Reset specific config files to defaults (backs up existing).

```bash
toolsetup reset               # Reset all
toolsetup reset --llm
toolsetup reset --workdir
toolsetup reset --youtube
toolsetup reset --agent
toolsetup reset --force       # Skip confirmation
```

### `toolsetup reset-all`

Create fresh default configs for all fast-market tools (backs up existing).

```bash
toolsetup reset-all
toolsetup reset-all --force
toolsetup reset-all --provider anthropic --workdir /path/to/workdir
```

---

### `toolsetup autocomplete`

Manage shell autocompletion for all fast-market CLIs.

```bash
# Generate and install completions (bash by default)
toolsetup autocomplete configure

# For zsh / fish
toolsetup autocomplete configure --shell zsh
toolsetup autocomplete configure --shell fish

# Force regeneration (after adding new tools)
toolsetup autocomplete configure --force

# List discovered CLI tools
toolsetup autocomplete list

# Shorthand alias
toolsetup autocomplete-configure
```

After running, add to `~/.bashrc`:

```bash
source ~/.config/fast-market/completions/fast-market.bash
```

---

### `toolsetup backup`

Snapshot and restore workdir, config, and data directories.

```bash
# Snapshot all directories
toolsetup backup snapshot

# Snapshot a specific directory
toolsetup backup snapshot --source-type workdir
toolsetup backup snapshot --source-type config
toolsetup backup snapshot --source-type data

# Snapshot specific files within a directory
toolsetup backup snapshot --source-type workdir --target myfile.json

# Restore from current snapshot
toolsetup backup restore --source-type workdir
toolsetup backup restore --source-type config

# Rollback to a specific snapshot
toolsetup backup rollback --source-type workdir
toolsetup backup rollback --source-type workdir my-snapshot-name

# Show backup status
toolsetup backup status --source-type workdir
toolsetup backup status --source-type config

# List all snapshots
toolsetup backup list
toolsetup backup list --source-type workdir
```

---

### `toolsetup config`

Manage XDG config directory.

```bash
# Remove all *.bak* files from config directory
toolsetup config clean-bak

# Dry run (show what would be removed)
toolsetup config clean-bak --dry-run
```

### `toolsetup data`

Inspect XDG data directory.

```bash
# List contents of ~/.local/share/fast-market/
toolsetup data
toolsetup data list
```

---

## Architecture

```
toolsetup-cli/
├── cli.py                          # Entry: wires all command groups
├── toolsetup_entry/__init__.py     # Package entry point
└── commands/
    ├── setup/
    │   ├── register.py             # Main toolsetup group (llm, path, edit, show, reset, diagnose)
    │   ├── workdir.py              # toolsetup workdir subgroup
    │   ├── diagnose.py             # Health check logic
    │   └── plugins/                # Config plugins (llm, workdir, youtube, agent)
    ├── autocomplete/register.py    # Shell completion generation
    ├── backup/register.py          # Snapshot/restore commands
    ├── config/register.py          # Config directory utilities
    ├── data/register.py            # Data directory listing
    ├── discovery.py                # Discover all *-cli tools in monorepo
    └── snapshot_service.py         # Tar-based snapshot/restore logic
```

See [AGENTS.md](AGENTS.md) for module-level contributor guidance.

## Troubleshooting

### "Provider not configured"

Run `toolsetup llm add <provider>` first, then retry.

### LLM call fails (API key missing)

`toolsetup` only stores the env var name. Export the actual key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### Workdir locked, can't navigate

```bash
toolsetup workdir islocked
toolsetup workdir unlock
# or
toolsetup workdir release --bypass   # Unlock + create new workdir immediately
```

### Shell completions not working

Re-generate after adding new tools:

```bash
toolsetup autocomplete configure --force
source ~/.config/fast-market/completions/fast-market.bash
```

## Development / Testing

Integration tests run across the monorepo:

```bash
pytest tests/ -v
```

See [AGENTS.md](AGENTS.md) for extension points and config plugin architecture.
