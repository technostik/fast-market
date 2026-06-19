# task-agent

Agentic task execution CLI — drives an LLM to iteratively run whitelisted CLI commands until a task is complete.

## Installation

```bash
cd task-cli
pip install -e .
```

Requires an LLM provider configured via `toolsetup`.

## Configuration

- **Agent config** (shared with skill-cli): `~/.config/fast-market/common/agent/config.yaml`
- **Common config** (`workdir`, `llm`): `~/.config/fast-market/common/config.yaml`

First-time setup:
```bash
toolsetup    # configure LLM provider
```

## CLI Reference

The CLI binary is `task`. The default command is `apply`, so `task "description"` is equivalent to `task apply "description"`.

---

### `task apply`

Execute a task with LLM-driven command loop.

```bash
# Basic usage (shorthand: default command)
task "list files and summarize"

# Explicit apply
task apply "list files and summarize"

# Specific provider/model, explicit workdir
task "analyze data.csv" -P anthropic -m claude-sonnet-4-6 -w ./sandbox

# With parameters
task "search corpus for {topic}" -p topic="AI safety" -p limit=20

# Load task description from file
task apply --from-file task.md -p config=@config.yaml

# Dry run — shows system prompt without executing
task apply "create hello.txt" -w /tmp --dry-run

# Save session YAML (relative = relative to workdir)
task "complex task" --save-session session.yaml

# Suppress session header and metrics
task "quick task" --silent

# Debug mode
task "debug task" --debug full
```

**Options:**

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--from-file` | `-f` | Load task description from file | |
| `--workdir` | `-w` | Working directory | common config or `.` |
| `--param` | `-p` | `key=value` parameter (repeatable) | |
| `--provider` | `-P` | LLM provider | from common config |
| `--model` | `-m` | LLM model | from provider config |
| `--max-iterations` | `-i` | Max tool calls before stopping | 20 |
| `--timeout` | `-t` | Timeout per command (seconds) | 60 |
| `--llm-timeout` | | Timeout per LLM call (0 = no limit) | 0 |
| `--dry-run` | `-n` | Show system prompt without executing | |
| `--debug` | `-d` | `normal` or `full` debug output | |
| `--format` | `-F` | `text` or `json` output | text |
| `--silent` | `-s` | Suppress session header and metrics | |
| `--save-session` | `-o` | Save session YAML to this path | `.last-session.yaml` in workdir |

**Parameter resolution:**
- `key=value` — literal string
- `key=@-` — read from stdin
- `key=@filename` — read from file relative to workdir

**Session metrics** (printed to stderr after completion):
```
── Session Metrics ──────────────────────────
  Tool calls : 8
  Rounds     : 5
  Errors     : 1
  Guesses    : 0
  Success    : 88%
────────────────────────────────────────────
```

---

### `task report`

Show metrics and failed commands from a saved session file.

```bash
task report session.yaml
task report session.yaml --format json | jq '.failures'
```

---

### `task setup`

Manage task-specific configuration.

```bash
# Show current config
task setup show

# Edit config in default editor
task setup edit

# Show path to config file
task setup --path
```

#### Allowed Commands

```bash
task setup allowed-commands list
task setup allowed-commands add python3            # auto-detected as system command
task setup allowed-commands add corpus tool        # explicitly as fast-market tool
task setup allowed-commands remove rm system       # explicitly from system_commands
task setup allowed-commands remove corpus          # searches both categories
```

#### Limits and Defaults

```bash
task setup set-max-iterations 50
task setup set-timeout 120        # per-command timeout in seconds
task setup set-workdir /path/to/default/workdir
```

#### Reset

```bash
task setup reset    # Reset agent config to defaults (shared with skill-cli)
```

---

### `task prompt`

Manage agent prompt templates (system prompt and command-docs templates).

```bash
task prompt list
task prompt show default
task prompt set my-custom-prompt
task prompt edit my-prompt
```

---

### `task show-sys-prompt`

Render the full system prompt that would be sent to the LLM, for inspection and debugging.

```bash
task show-sys-prompt "my task description"
task show-sys-prompt "analyze {file}" -w ./sandbox -p file=data.csv
```

---

## Security Model

| Layer | Protection |
|-------|------------|
| Whitelist | Only basename-matched commands allowed |
| No `shell=True` | Prevents shell injection |
| Workdir jail | Rejects absolute paths from LLM; blocks system dirs |
| Per-command timeout | Prevents hung processes |
| Max iterations | Prevents infinite loops |

**Forbidden workdirs:** `/`, `/bin`, `/sbin`, `/usr`, `/lib`, `/lib64`, `/etc`, `/sys`, `/proc`, `/dev`

## Default Allowed Commands

**Fast-market tools:** `corpus`, `image`, `youtube`, `message`, `prompt`, `task`

**System commands:** `ls`, `cat`, `grep`, `find`, `echo`, `head`, `tail`, `wc`, `mkdir`, `touch`, `rm`, `cp`, `mv`, `sort`, `uniq`, `awk`, `sed`, `jq`

## Architecture

```
task-cli/
├── task_entry/              # Entry point — discovers providers, wires CLI
├── commands/
│   ├── task/
│   │   ├── register.py      # apply command definition
│   │   ├── executor.py      # Command validation & subprocess execution
│   │   ├── loop.py          # Re-exports TaskLoop from common.agent
│   │   ├── prompts.py       # System prompt builder
│   │   └── command_registry.py  # Auto-extracts --help from fast-market CLIs
│   ├── show_sys_prompt/     # Debug: render full system prompt
│   └── setup/               # Configuration management
│       ├── register.py      # Setup subcommands
│       └── task_edit.py     # Config editor + validation
└── core/
    ├── session.py           # Re-exports Session from common.agent
    └── task_prompt.py       # TaskPromptConfig dataclass
```

The agentic loop (`TaskLoop`) lives in `common/agent/` — task-cli owns only the CLI layer.

## Troubleshooting

**`Error: No default LLM provider configured.`** — Run `toolsetup` to configure a provider.

**`Error: Provider 'X' not available.`** — Provider not installed or config mismatch; run `toolsetup` to reconfigure.

**Forbidden workdir error** — task rejects system directories; use a safe path (e.g. `/tmp/mytask`).

**Command not in whitelist** — `task setup allowed-commands add <cmd>`.

**`--debug full`** to dump the full session YAML when the LLM behaves unexpectedly.

## Development / Testing

```bash
# Install
pip install -e .

# Dry run (no LLM call)
task apply "hello world" --dry-run

# Quick smoke test
task "echo hello" -w /tmp --timeout 10

# Review last session
task report /tmp/.last-session.yaml
```

Contributors: see [`AGENTS.md`](AGENTS.md) for module-level guidance.
