# prompt task — Agentic Task Execution

Execute complex, multi-step tasks using an LLM that iteratively runs CLI commands in a sandboxed environment.

## Quick Start

```bash
# Most basic usage
prompt task "list all files in this directory"

# With a working directory
prompt task "analyze data.csv and create a summary" --workdir ./research

# With parameters
prompt task "search corpus for {topic}" --param topic="AI safety"

# Dry run to see what would happen
prompt task "create a report" --workdir ./output --dry-run
```

## Core Concepts

### Task Description
The task is a natural language description of what you want accomplished. You can use placeholders like `{variable}` that will be substituted with parameter values.

### Working Directory
All commands execute within the specified `--workdir`. The directory is created if it doesn't exist. You cannot escape the sandbox into system directories.

### Task Parameters
Parameters provide context and data to the task:

| Syntax | Meaning |
|--------|---------|
| `--param key=value` | Literal string |
| `--param key=@filename` | Read from file in workdir |
| `--param key=@-` | Read from stdin |

Parameters are resolved before the task starts and injected into the system prompt.

### Allowed Commands
Only whitelisted commands can run. Default whitelist includes:
- **Fast-market tools**: `corpus`, `image`, `youtube`, `message`, `prompt`
- **File operations**: `ls`, `cat`, `grep`, `find`, `jq`
- **Utilities**: `echo`, `head`, `tail`, `wc`, `mkdir`, `touch`, `rm`, `cp`, `mv`, `sort`, `uniq`, `awk`, `sed`

Manage with:
```bash
prompt setup task-commands list
prompt setup task-commands add python3
prompt setup task-commands remove rm
```

## Examples

### Example 1: Knowledge Search

Search the corpus and create a summary file:

```bash
prompt task "search the corpus for {query}, save top 5 results to summary.md" \
  --param query="machine learning best practices" \
  --workdir ./research
```

The agent will:
1. Run `corpus search "machine learning best practices"`
2. Analyze the results
3. Create `summary.md` with findings

### Example 2: Data Analysis

Analyze a CSV file and extract insights:

```bash
# First, ensure you have data.csv in the workdir
prompt task "analyze sales.csv: count rows, find highest value, list top 5 products by revenue" \
  --workdir ./data_analysis
```

Expected workflow:
1. `ls` to find the file
2. `head` or `cat` to view structure
3. `grep` or `awk` to process data
4. Create output files

### Example 3: Using Stdin

Pipe data into a task:

```bash
echo "interesting topics" | \
prompt task "search corpus for each topic, save results to {topic}.md" \
  --param topic=@- \
  --workdir ./research
```

### Example 4: From File Input

Load task description from a file:

```bash
# Create task file
cat > analyze_task.md << 'EOF'
Analyze the data in input.csv:
1. Count total rows
2. Find columns with missing values
3. Calculate averages for numeric columns
4. Create report.md with findings
EOF

# Create input file
cat > input.csv << 'EOF'
name,age,city
Alice,30,NYC
Bob,25,LA
EOF

# Run task
prompt task --from-file analyze_task.md --workdir ./output
```

### Example 5: With Config File

Pass configuration to the task:

```bash
# Create config
cat > config.json << 'EOF'
{
  "model": "gpt-4",
  "temperature": 0.7,
  "max_results": 10
}
EOF

prompt task "load config.json, search corpus with parameters, save results" \
  --param config=@config.json \
  --workdir ./output
```

### Example 6: Image Generation Workflow

Generate images and save metadata:

```bash
prompt task "
1. Search corpus for 'sunset landscape'
2. Use image generate to create 3 variations
3. Save image URLs to images.json
" --workdir ./generated
```

### Example 7: YouTube Research

Research a topic on YouTube:

```bash
prompt task "
1. Search youtube for 'Python tutorial'
2. List top 5 videos with titles and URLs
3. Create research.md with findings
" --workdir ./youtube_research
```

### Example 8: Dry Run Mode

Preview commands before execution:

```bash
prompt task "create hello.txt with 'Hello World'" \
  --workdir ./test \
  --dry-run
```

Output:
```
[DRY RUN] Task: create hello.txt with 'Hello World'
[DRY RUN] Workdir: /path/to/test
[DRY RUN] Max iterations: 20
[DRY RUN] Allowed commands: corpus, image, ls, cat, echo, ...
[DRY RUN] Note: Commands not actually executed in dry-run mode.
```

### Example 9: Custom Provider

Use a specific LLM provider:

```bash
# Use Ollama for local inference
prompt task "analyze logs" --provider ollama --workdir ./logs

# Use specific model
prompt task "summarize document" \
  --provider anthropic \
  --model claude-haiku-4-20250514 \
  --workdir ./docs
```

### Example 10: Recursive Task

The `prompt` command is allowed, enabling meta-tasks:

```bash
prompt task "
1. Create a new prompt template 'analyze_data'
2. Use prompt apply to execute it with data.csv
3. Save results
" --workdir ./automation
```

### Example 11: Iteration Control

Limit or extend iteration count:

```bash
# Quick task (5 iterations max)
prompt task "simple task" --max-iterations 5 --workdir ./test

# Complex task (50 iterations)
prompt task "thorough research task" --max-iterations 50 --workdir ./deep_dive
```

### Example 12: Timeout Control

Adjust command timeout:

```bash
# Quick commands only (10 second timeout)
prompt task "count lines" --timeout 10 --workdir ./count

# Long-running commands (5 minute timeout)
prompt task "index all files" --timeout 300 --workdir ./index
```

### Example 13: Session Management

Control how task sessions are displayed and saved:

```bash
# Normal mode shows session header
prompt task "analyze data" --workdir ./research
# Output includes session header:
# ============================================================
# TASK SESSION: analyze data
# Provider: anthropic, Model: claude-sonnet-4-20250514
# Workdir: /path/to/research
# ============================================================

# Suppress session output
prompt task "quick task" --silent --workdir ./test

# Save session to YAML for later review
prompt task "complex analysis" --save-session session.yaml --workdir ./output

# Debug mode shows full session in YAML format
prompt task "debug task" --debug full --workdir ./test
```

## Configuration

Edit `~/.local/share/fast-market/config/prompt.yaml`:

```yaml
task:
  allowed_commands:
    - corpus
    - image
    - ls
    - cat
    - jq
    # ... add more as needed
  max_iterations: 20      # Max tool calls per task
  default_timeout: 60     # Seconds per command
  active_prompt: default  # Active task prompt name
```

Or use the setup command:

```bash
# List current config
prompt setup task-commands list

# Add a new allowed command
prompt setup task-commands add python3

# Remove a command
prompt setup task-commands remove rm

# Adjust limits
prompt setup task set-max-iterations 50
prompt setup task set-timeout 120
```

### Custom Task Prompts

You can customize the system prompt used by `prompt task`:

```bash
# List available prompts
prompt setup task-prompts list

# Set active prompt
prompt setup task-prompts set my-custom-prompt

# Reset to built-in default
prompt setup task-prompts set default

# Edit a custom prompt
prompt setup task-prompts edit my-custom-prompt

# Import from YAML file
prompt setup task-prompts import ./custom-prompt.yaml
```

Prompts are stored in `~/.local/share/fast-market/task_prompts/` as YAML files.

## Security

| Protection | How |
|------------|-----|
| Command whitelist | Only listed commands can run |
| No shell=True | Prevents command injection |
| Workdir jail | Can't escape to system directories |
| Absolute path rejection | Commands can't reference `/etc/passwd` etc. |
| Per-command timeout | Default 60s, prevents hangs |
| Max iterations | Default 20, prevents infinite loops |

## Tips

### Writing Good Tasks

**Do:**
- Be specific about the end goal
- Mention expected output format
- List any input files or parameters
- Break complex tasks into numbered steps

**Don't:**
- Ask for impossible things (e.g., "install system packages")
- Use absolute paths (they're rejected)
- Expect external network access beyond allowed commands

### Debugging

```bash
# Verbose mode shows internal steps
prompt task "task" --workdir ./test -v

# Dry run first
prompt task "task" --workdir ./test --dry-run

# Start simple, iterate
prompt task "list files" --workdir ./test
```

### Common Patterns

**Search and Summarize:**
```bash
prompt task "search corpus for {q}, create summary.md with key points" \
  --param q="your topic"
```

**Process and Transform:**
```bash
prompt task "read data.json, transform to CSV, save as data.csv" \
  --workdir ./transform
```

**Batch Operations:**
```bash
prompt task "for each .txt file: count words, create {name}.stats" \
  --workdir ./batch
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Task completed successfully |
| 1 | Error during execution |
| 124 | Command timed out |

## See Also

- `prompt setup --help` — Configure providers and task settings
- `prompt setup task-prompts --help` — Prompt management options
- [corpus search](../corpus-agent/) — Knowledge search
- [image generate](../image-agent/) — Image generation
