# commands/task

## Purpose
Sandboxed agentic loop where an LLM can iteratively execute whitelisted CLI commands until task completion.

## Architecture

```
prompt task "analyze data.csv" --workdir ./sandbox
    │
    ▼
┌─────────────────────────────────────────┐
│           Agentic Loop                   │
│  1. Send task + history to LLM           │
│  2. LLM responds with tool_use or done   │
│  3. Execute command in workdir           │
│  4. Capture output, append to history   │
│  5. Repeat until completion/max_iter    │
└─────────────────────────────────────────┘
```

## Key Components

- **executor.py**: Command validation, whitelist checking, subprocess execution
- **loop.py**: Agentic loop with Anthropic tool use protocol
- **register.py**: Click command interface
- **prompts.py**: System prompt builder with command documentation
- **command_registry.py**: Auto-extraction of fast-market command help

## Security Model

| Layer | Protection |
|-------|------------|
| Whitelist | Only basename-matched commands allowed |
| No shell=True | Prevents injection attacks |
| Workdir jail | cwd=workdir, reject absolute paths |
| Timeout | Per-command timeout (default 60s) |
| Max iterations | Prevents infinite loops |

## Default Allowed Commands

- `corpus` - Knowledge search
- `image` - Image generation
- `youtube` - YouTube tools
- `message` - Messaging
- `prompt` - Recursive (counts toward max_iterations)
- `ls`, `cat`, `jq`, `grep`, `find` - File operations
- `echo`, `head`, `tail`, `wc` - Utilities

## Task Parameters

Parameters can be passed with `--param key=value`. Values starting with `@` are resolved:
- `@-` reads from stdin
- `@filename` reads from a file in the workdir

Parameters are injected into the system prompt so the LLM knows context without re-entering it.

```bash
# Literal parameter
prompt task "summarize {topic}" --param topic="AI trends"

# From file
prompt task "analyze data" --param input=@data.csv

# From stdin
echo "search query" | prompt task "search corpus" --param query=@-
```

## Command Auto-Description

The system automatically generates documentation for allowed commands:

1. **Fast-Market commands** (corpus, image, youtube, message, prompt): Help text is auto-extracted by running `--help`
2. **System commands** (ls, cat, jq, grep, etc.): Pre-written documentation with examples

This gives the LLM detailed information about available commands without manual documentation.

## Configuration

In `~/.local/share/fast-market/config/prompt.yaml`:
```yaml
task:
  allowed_commands:
    - corpus
    - image
    - ...
  max_iterations: 20
  default_timeout: 60
```

Manage with:
```bash
prompt setup --list-task-commands
prompt setup --add-task-command python3
prompt setup --set-task-max-iterations 50
```

## Usage

```bash
# Basic task
prompt task "list files and summarize" --workdir ./test

# With specific provider/model
prompt task "analyze data.csv" --workdir ./sandbox --provider anthropic --model claude-sonnet-4-20250514

# With parameters
prompt task "search corpus for {topic}" --param topic="AI safety" --workdir ./research

# Dry run (show commands without executing)
prompt task "create hello.txt" --workdir ./test --dry-run

# Load task from file with attached parameters
prompt task --from-file task.md --param config=@config.yaml
```
