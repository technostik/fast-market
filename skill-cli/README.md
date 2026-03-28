# skill-agent

CLI tool for managing skills stored in `~/.local/share/fast-market/skills/`. Skills are reusable prompt templates with optional executable scripts.

## Installation

```bash
pip install skill-agent
```

Or install from source:

```bash
cd skill-cli
pip install -e .
```

### Dependencies

- `click >= 8.1`
- `auto-click-auto >= 0.1.0`
- `pyyaml >= 6.0`

For running skills with LLM execution:
- `llm` extra: `pip install skill-agent[llm]`

## Configuration

Skills are stored in `~/.local/share/fast-market/skills/` (XDG-compliant).

No configuration required for basic usage. For LLM-powered commands (`run`, `apply`), configure an LLM provider in your common config:

```yaml
# ~/.config/fast-market/config.yaml
llm:
  provider: openai
  model: gpt-4
  api_key: your-api-key
```

## Skills Structure

A skill is a directory containing:

- `SKILL.md` — Required. Skill definition with YAML frontmatter
- `LEARN.md` — Optional. Learned information from skill execution
- `scripts/` — Optional. Executable scripts

```text
my-skill/
├── SKILL.md       # Skill definition (required)
├── LEARN.md       # Learned lessons (optional)
└── scripts/        # Executable scripts (optional)
    └── run.sh
```

### SKILL.md Format

```markdown
---
name: my-skill
description: What this skill does
max_iterations: 10
timeout: 300
autocompact: 40
---

# My Skill

## When to use this skill
Describe when to use this skill.

## Instructions
Step-by-step instructions.
```

**Frontmatter options:**
- `name` — Skill name (defaults to directory name)
- `description` — Brief description
- `max_iterations` — Max LLM iterations for prompt-based skills
- `timeout` — Execution timeout in seconds (0 = no timeout)
- `llm_timeout` — LLM call timeout in seconds
- `autocompact` — Auto-compact LEARN.md when exceeding this many lines

## CLI Reference

### skill list

List all available skills.

```bash
skill list                    # List skills
skill list --format json      # JSON output
```

### skill show

Show skill details.

```bash
skill show <name>             # Show SKILL.md content
skill show <name> --learned   # Show LEARN.md instead
skill show <name> -l          # Short form for --learned
```

### skill create

Create a new skill scaffold.

```bash
skill create <name>                    # Create skill
skill create <name> -d "description"   # With description
skill create <name> -s                  # With scripts directory
```

### skill delete

Delete a skill.

```bash
skill delete <name>           # With confirmation
skill delete <name> --force   # Skip confirmation
skill delete <name> -f        # Short form
```

### skill edit

Edit skill files.

```bash
skill edit <name>                     # Edit SKILL.md
skill edit <name> --learned           # Edit LEARN.md
skill edit <name> -l                  # Short form
skill edit <name> script.sh           # Edit specific file
skill edit <name> script.sh --create  # Create if doesn't exist
skill edit <name> script.sh -c        # Short form
```

### skill apply

Apply (execute) a skill.

```bash
skill apply <skill-name>                          # Execute skill
skill apply <skill-name>/<script>                 # Execute specific script
skill apply <skill-name> KEY=VALUE               # Pass parameters
skill apply <skill-name> -w /path                 # Working directory (default: common config workdir)
skill apply <skill-name> -t 60                    # Timeout (seconds, 0=no timeout)
skill apply <skill-name> -i 5                     # Max iterations
skill apply <skill-name> -n                      # Dry run
skill apply <skill-name> -L                      # Auto-learn after execution
skill apply <skill-name> -C                      # Use compacting prompt to consolidate learnings
skill apply <skill-name> --format json           # JSON output
skill apply <skill-name> -P openai -m gpt-4      # LLM provider/model
skill apply <skill-name> --save-session file.yaml  # Save session to file
```

### skill run

Orchestrate multiple skills to accomplish complex tasks (requires LLM).

```bash
skill run "your task description"                 # Run with default LLM
skill run "task" -P openai -m gpt-4               # Specific provider
skill run "task" -w /path                         # Working directory
skill run "task" -i 20                           # Max iterations
skill run "task" -v                              # Verbose output
```

### skill path

Print skills directory path.

```bash
skill path
```

### skill completion

Print shell completion instructions.

```bash
skill completion           # Show all shells
skill completion bash      # Bash only
skill completion zsh      # Zsh only
skill completion fish     # Fish only
```

### skill auto-learn

Manage auto-learn prompt templates.

```bash
skill auto-learn path              # Show config path
skill auto-learn show             # Show learn_analysis_prompt (how to analyze sessions)
skill auto-learn show --result    # Show learn_result_template (expected LEARN.md format)
skill auto-learn show --compact   # Show learn_compacting_prompt (how to consolidate learnings)
skill auto-learn edit            # Edit learn_analysis_prompt
skill auto-learn edit --result   # Edit learn_result_template
skill auto-learn edit --compact   # Edit learn_compacting_prompt
skill auto-learn compact <skill>  # Compact LEARN.md using LLM
skill auto-learn compact <skill> -n 20  # Compact to 20 lines
```

## Auto-Learn Templates

The auto-learn system uses three configurable templates:

1. **learn_analysis_prompt** — How the LLM should analyze sessions to extract lessons
2. **learn_result_template** — The expected format/structure of LEARN.md output
3. **learn_compacting_prompt** — How to consolidate multiple learnings into one

Templates are stored in `~/.config/fast-market/skill/config.yaml` and support placeholders:
- `{task_description}`, `{skill_name}`, `{outcome}`, `{iterations_used}`, `{max_iterations}`, `{params_summary}`, `{session_log}`, `{learn_result_template}`, `{max_lines}`

**Compacting:**
```bash
skill auto-learn compact myskill     # Compact to default (80 lines)
skill auto-learn compact myskill -n 30  # Compact to 30 lines
```

## Features

- **Skill Management** — Create, list, show, edit, delete skills
- **Script Execution** — Run executable scripts within skills
- **LLM Integration** — Apply skills with LLM providers, auto-learn from execution
- **Parameter Passing** — Pass `KEY=VALUE` parameters to skills
- **Working Directory** — Execute skills in specific directories (defaults to common config workdir)
- **Auto-Learn** — Automatically extract lessons from executions to LEARN.md
- **Auto-Compact** — Automatically consolidate learnings when exceeding line threshold
- **Dry Run** — Preview execution without running
- **JSON Output** — Machine-readable output for piping
- **Shell Completion** — Bash, Zsh, Fish support
- **LEARN.md** — Track learned information from skill execution

## Examples

### List skills as JSON

```bash
skill list --format json | jq '.[] | .name'
```

### Edit a skill file

```bash
skill edit my-skill
```

### Execute a skill with parameters

```bash
skill apply github-summary repo=owner/repo format=markdown
```

### Dry run a skill

```bash
skill apply complex-task -n --format json
```

### Apply with auto-learn and compacting

```bash
skill apply myskill --auto-learn --compact
```

### Chain skills

```bash
skill run "Analyze the codebase and create a summary"
```

## Architecture

```
skill-cli/
├── cli/main.py           # Entry point
├── commands/             # Command implementations
│   ├── list/            # List skills
│   ├── show/            # Show skill details
│   ├── create/          # Create new skill
│   ├── delete/          # Delete skill
│   ├── edit/            # Edit skill files
│   ├── apply/           # Execute skill
│   ├── run/             # Orchestrate skills (LLM)
│   ├── path/            # Show skills path
│   ├── auto_learn/      # Auto-learn management
│   └── params.py        # Custom Click types
├── core/                # Core functionality
└── skill_entry/         # Package entry point
```

## Development

```bash
# Install in development mode
pip install -e .

# Run tests (if available)
pytest

# Lint
ruff check .
```
