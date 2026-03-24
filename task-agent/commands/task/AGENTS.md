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
  active_prompt: default  # Custom prompt name

tools_doc_prompt: default  # Tools doc prompt name
```

Manage with:
```bash
prompt setup --list-task-commands
prompt setup --add-task-command python3
prompt setup --set-task-max-iterations 50

# Task prompt management
prompt setup --list-task-prompts
prompt setup --set-task-prompt my-prompt
prompt setup --edit-task-prompt my-prompt
prompt setup --show-task-prompt my-prompt
prompt setup --import-task-prompt file.yaml

# Tools doc prompt management
prompt setup --list-tools-doc-prompts
prompt setup --set-tools-doc-prompt my-tools-doc
prompt setup --edit-tools-doc-prompt my-tools-doc
prompt setup --show-tools-doc-prompt my-tools-doc
prompt setup --import-tools-doc-prompt file.yaml

# Preview
prompt setup --show-task-tools   # Preview inner tool documentation
```

- Task prompts stored in `~/.local/share/fast-market/task_prompts/`
- Tools doc prompts stored in `~/.local/share/fast-market/tools_doc_prompts/`

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

# Save session to file
prompt task "complex task" --workdir ./output --save-session session.yaml

# Suppress session output
prompt task "quick task" --silent --workdir ./test

# Debug mode shows full session
prompt task "debug task" --debug full --workdir ./test
```

## Session Display

Each task run displays a session header with task details:

```
============================================================
TASK SESSION: analyze data.csv
Provider: anthropic, Model: claude-sonnet-4-20250514
Workdir: /path/to/research
Parameters:
  file: data.csv
============================================================
```

The session tracks:
- Task description
- Provider and model
- Working directory
- Parameters
- All turns, tool calls, and results
