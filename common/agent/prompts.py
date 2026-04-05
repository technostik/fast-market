from __future__ import annotations

from pathlib import Path


DEFAULT_AGENT_PROMPT_TEMPLATE = """You are a command execution agent. You have access to a sandboxed command-line environment to accomplish tasks.

# Your Task
{task_description}
{params_section}

# Working Directory
All commands execute in a working directory: USE RELATIVE PATHS ONLY. DO NOT USE ABSOLUTE PATHS.
You can read and write files in this directory. Relative paths are resolved from here.

{env_vars_section}

---

{command_docs}

---

# How to Work

1. **Understand the task**: Break it down into clear steps
2. **Explore first**: Use --help if you're unsure how to proceed
3. **Execute incrementally**: Run one command, check the result, then decide next step
4. **Handle errors**: If a command fails, read the error message to try to correct it before trying another command
5. **Stay focused**: Only use commands that advance the task
6. **Finish clearly**: When done, summarize what you accomplished (without making tool calls)

# Critical Rules

- **Only use listed commands** - others will be rejected
- **Work within the directory** - you cannot escape `{workdir}`
- **Check outputs** - always verify command results before proceeding
- **Be efficient** - prefer one good command over many guesses
- **Ask for help** - if truly stuck, explain what you need
"""


DEFAULT_FASTMARKET_TOOLS = {
    "corpus": {
        "description": "Search and query your knowledge base with embeddings.",
        "commands": ["get-from-id", "get-from-source", "get-last", "list", "search"],
    },
    "image": {
        "description": "Generate images from text prompts using AI image generation APIs.",
        "commands": ["generate"],
    },
    "message": {
        "description": "Send messages and alerts via Telegram.",
        "commands": ["alert", "ask"],
    },
    "task": {
        "description": "Execute agentic task",
        "commands": ["apply"],
    },
    "youtube": {
        "description": "Search YouTube videos and manage comments via the YouTube Data API.",
        "commands": ["search", "comments", "reply", "get-transcript", "get-last"],
    },
    "prompt": {
        "description": "Generate prompts from text using AI prompt generation APIs.",
        "commands": ["apply", "list"],
    },
}

DEFAULT_SYSTEM_COMMANDS = [
    "ls",
    "cat",
    "jq",
    "grep",
    "find",
    "echo",
    "head",
    "tail",
    "wc",
    "mkdir",
    "touch",
    "rm",
    "cp",
    "mv",
    "sort",
    "uniq",
    "awk",
    "sed",
]


DEFAULT_PREPARATION_PROMPT = """You are a skill orchestrator. Before entering the planning loop,
read the goal and available skills, then produce a structured execution plan.

## Goal
{goal}

## Available Skills
{skills_list}

## Your Task

Analyze the goal and available skills. Produce a JSON object with your plan:

```json
{{
  "plan": "step by step description of intended approach",
  "success_criteria": "concrete, observable description of what done looks like",
  "risks": "what could go wrong and how to handle it"
}}
```

IMPORTANT: Use proper JSON escaping. If you need to use quotes inside a string, escape them with backslash (\") or use single quotes only when the outer string uses double quotes.

Be specific about the order of skills and what each step should accomplish.
"""


DEFAULT_EVALUATION_PROMPT = """You are evaluating whether the last step brought us closer to the goal.

## Goal
{goal}

## Success Criteria
{success_criteria}

## History
{history}

## Last Step Result
{last_summary}

## Your Task

Determine if the last step satisfied the success criteria. Return a JSON object:

```json
{{
  "satisfied": true or false,
  "reason": "one sentence explaining your assessment",
  "suggestion": "if not satisfied, what to try next"
}}
```

IMPORTANT: Use proper JSON escaping. If you need to use quotes inside a string, escape them with backslash (\") or use single quotes only when the outer string uses double quotes.

Be honest — if the goal isn't met, say so and suggest a different approach."""


DEFAULT_PLAN_PROMPT = """You are a skill orchestrator. Your job is to achieve a goal by
selecting and sequencing skills, one at a time.

## Goal
{goal}

## Success Criteria (what done looks like)
{success_criteria}

## Available Skills
{skills_list}

## History
{history}

## Instructions

Decide what to do next. You must return ONLY a JSON object.

### Actions

Run a specific skill:
{{
  "action": "run",
  "skill_name": "the-skill-name",
  "params": {{"key": "value"}},
  "reason": "one sentence why",
  "context_hint": "what the next skill will need from this result"
}}

Run a free-form task with raw CLI tools (use when no skill fits or a skill failed and you need to improvise):
{{
  "action": "task",
  "description": "detailed description of what to accomplish",
  "reason": "one sentence why no skill fits or why improvising is better",
  "context_hint": "what the next step will need from this result"
}}

Ask the user a question when you have genuine ambiguity you cannot resolve yourself:
{{
  "action": "ask",
  "question": "clear, specific question for the user",
  "reason": "one sentence why you need this information"
}}

Goal fully achieved:
{{
  "action": "done",
  "reason": "one sentence summary of what was accomplished"
}}

Goal cannot be achieved (repeated failures, missing capability):
{{
  "action": "fail",
  "reason": "one sentence explanation of why"
}}

### Rules
- Only use skills from the Available Skills list for "run" actions
- Use "task" when no skill fits OR when a skill failed and you want to try a different approach with raw tools
- Use "ask" sparingly — only when the goal is genuinely ambiguous, not just when a skill fails
- If a previous attempt failed, try a different approach (different skill, different params, or "task")
- Never repeat the exact same skill+params that already failed
- Params must be concrete values, not placeholders
- If a skill produced output that a next skill needs, it is available in history as context
- IMPORTANT: Use proper JSON escaping. If you need to use quotes inside a string, escape them with backslash (\") or use single quotes only when the outer string uses double quotes
"""


SYSTEM_COMMAND_DOCS = {
    "ls": {
        "description": "List directory contents",
        "usage": "ls [OPTIONS] [PATH]",
        "key_options": [
            "-l  : Long format with permissions and timestamps",
            "-a  : Show hidden files (starting with .)",
            "-h  : Human-readable file sizes",
            "-R  : Recursive listing",
        ],
        "examples": [
            "ls                    # List current directory",
            "ls -la               # Detailed listing including hidden files",
            "ls *.txt             # List only .txt files",
        ],
    },
    "cat": {
        "description": "Display file contents",
        "usage": "cat [FILE...]",
        "examples": [
            "cat file.txt         # Show file contents",
            "cat file1.txt file2.txt  # Show multiple files",
        ],
        "notes": "For large files, consider using head/tail to see parts",
    },
    "head": {
        "description": "Display first lines of file",
        "usage": "head [OPTIONS] [FILE]",
        "key_options": [
            "-n NUM : Show first NUM lines (default: 10)",
        ],
        "examples": [
            "head file.txt        # First 10 lines",
            "head -n 20 file.txt  # First 20 lines",
        ],
    },
    "tail": {
        "description": "Display last lines of file",
        "usage": "tail [OPTIONS] [FILE]",
        "key_options": [
            "-n NUM : Show last NUM lines (default: 10)",
        ],
        "examples": [
            "tail file.txt        # Last 10 lines",
            "tail -n 50 log.txt   # Last 50 lines of log",
        ],
    },
    "grep": {
        "description": "Search for patterns in files",
        "usage": "grep [OPTIONS] PATTERN [FILE...]",
        "key_options": [
            "-i  : Case-insensitive search",
            "-n  : Show line numbers",
            "-r  : Recursive directory search",
            "-v  : Invert match (show non-matching lines)",
        ],
        "examples": [
            "grep 'error' log.txt         # Find 'error' in log.txt",
            "grep -i 'warning' *.log      # Case-insensitive search in all .log files",
            "grep -n 'TODO' code.py       # Show line numbers for TODOs",
        ],
    },
    "find": {
        "description": "Find files by name or properties",
        "usage": "find [PATH] [OPTIONS]",
        "key_options": [
            "-name PATTERN : Find by filename pattern",
            "-type f       : Only files",
            "-type d       : Only directories",
        ],
        "examples": [
            "find . -name '*.txt'         # All .txt files in current dir",
            "find . -name 'test*'         # Files starting with 'test'",
            "find . -type f -name '*.py'  # All Python files",
        ],
    },
    "wc": {
        "description": "Count lines, words, and characters",
        "usage": "wc [OPTIONS] [FILE...]",
        "key_options": [
            "-l  : Count lines only",
            "-w  : Count words only",
            "-c  : Count characters only",
        ],
        "examples": [
            "wc file.txt          # Lines, words, chars",
            "wc -l data.csv       # Count lines in CSV",
        ],
    },
    "jq": {
        "description": "Parse and query JSON data",
        "usage": "jq [FILTER] [FILE]",
        "key_filters": [
            ".              : Pretty-print entire JSON",
            ".key           : Extract value of 'key'",
            ".[]            : Iterate array elements",
            ".[0]           : First array element",
            ".key1.key2     : Nested access",
            "select(...)    : Filter elements",
        ],
        "examples": [
            "cat data.json | jq '.'                # Pretty-print",
            "cat data.json | jq '.results[]'       # Iterate results array",
            "cat data.json | jq '.[].name'         # Extract all names",
            "cat data.json | jq '.[] | select(.age > 30)'  # Filter by condition",
        ],
        "notes": "Input must be valid JSON. Use cat or command output as input.",
    },
    "echo": {
        "description": "Print text to stdout",
        "usage": "echo [TEXT]",
        "examples": [
            "echo 'Hello World'   # Print text",
            "echo $VAR            # Note: shell variables don't work in this sandbox",
        ],
        "notes": "Useful for creating simple text files or testing",
    },
    "mkdir": {
        "description": "Create directories",
        "usage": "mkdir [OPTIONS] DIRECTORY...",
        "key_options": [
            "-p  : Create parent directories as needed",
        ],
        "examples": [
            "mkdir output                  # Create single directory",
            "mkdir -p data/processed       # Create nested directories",
        ],
    },
    "rm": {
        "description": "Remove files or directories",
        "usage": "rm [OPTIONS] FILE...",
        "key_options": [
            "-r  : Recursive (for directories)",
            "-f  : Force (no confirmation)",
        ],
        "examples": [
            "rm file.txt          # Remove file",
            "rm -r temp/          # Remove directory and contents",
        ],
        "notes": "Use carefully - no undo!",
    },
    "cp": {
        "description": "Copy files or directories",
        "usage": "cp [OPTIONS] SOURCE DEST",
        "key_options": [
            "-r  : Recursive (for directories)",
        ],
        "examples": [
            "cp file.txt backup.txt       # Copy file",
            "cp -r folder/ backup/       # Copy directory",
        ],
    },
    "mv": {
        "description": "Move or rename files",
        "usage": "mv SOURCE DEST",
        "examples": [
            "mv old.txt new.txt           # Rename file",
            "mv file.txt folder/          # Move to directory",
        ],
    },
    "sort": {
        "description": "Sort lines of text",
        "usage": "sort [OPTIONS] [FILE]",
        "key_options": [
            "-r  : Reverse sort",
            "-n  : Numeric sort",
            "-u  : Unique (remove duplicates)",
        ],
        "examples": [
            "sort data.txt        # Sort alphabetically",
            "sort -n numbers.txt  # Sort numerically",
        ],
    },
    "uniq": {
        "description": "Remove duplicate adjacent lines",
        "usage": "uniq [FILE]",
        "examples": [
            "sort data.txt | uniq         # Remove duplicates (must sort first)",
        ],
        "notes": "Only removes adjacent duplicates - combine with sort",
    },
    "awk": {
        "description": "Pattern scanning and text processing",
        "usage": "awk 'PATTERN { ACTION }' [FILE]",
        "key_options": [
            "-F sep  : Field separator (default: whitespace)",
            "-v var=val  : Set variable",
        ],
        "examples": [
            "awk '{print $1}' file.txt     # Print first column",
            "awk -F, '{print $2}' data.csv  # Print second column of CSV",
            "awk '/error/ {print $0}' log.txt  # Print lines containing 'error'",
        ],
    },
    "sed": {
        "description": "Stream editor for text transformation",
        "usage": "sed [OPTIONS] 'SCRIPT' [FILE]",
        "key_options": [
            "-i  : Edit files in place",
            "s/old/new/  : Replace 'old' with 'new'",
        ],
        "examples": [
            "sed 's/old/new/g' file.txt   # Replace all occurrences",
            "sed -i 's/foo/bar/' file.txt # Edit in place",
            "sed -n '5p' file.txt         # Print line 5",
        ],
    },
    "touch": {
        "description": "Create empty files or update timestamps",
        "usage": "touch [OPTIONS] FILE...",
        "examples": [
            "touch newfile.txt     # Create empty file",
            "touch *.txt           # Update timestamps of all .txt files",
        ],
    },
}

TOOLS_DOC_TEMPLATES = {
    "full": "{aliases}{fastmarket_tools}{system_commands}{other_commands}",
    "minimal": "{aliases}{fastmarket_tools_minimal}{system_commands_minimal}{other_commands_minimal}",
}

DEFAULT_COMMAND_DOCS_TEMPLATES = {
    "full": {
        "description": "Verbose with full documentation",
        "template": "{aliases}{fastmarket_tools}{system_commands}",
    },
    "minimal": {
        "description": "Brief with descriptions",
        "template": "{fastmarket_tools_brief}{system_commands_minimal}",
    },
}


def _build_minimal_tools_section(commands: list[str], section_name: str) -> str:
    """Build minimal section with just command names."""
    if not commands:
        return ""
    names = ", ".join(f"`{c}`" for c in sorted(commands))
    heading = section_name.replace("**", "").replace("*", "")
    return f"## {heading}\n\n{names}\n"


def format_fastmarket_tool_minimal(cmd_name: str) -> str:
    """Format minimal fastmarket tool doc."""
    try:
        from commands.task.command_registry import get_fastmarket_command_help
    except ImportError:

        def get_fastmarket_command_help(cmd):
            return None

    info = get_fastmarket_command_help(cmd_name)
    if info:
        return f"`{info.name}`"
    return f"`{cmd_name}`"


def format_other_command_minimal(cmd_name: str) -> str:
    """Format minimal other command doc."""
    return f"`{cmd_name}`"


def format_alias_minimal(alias_name: str, alias_data) -> str:
    """Format minimal alias doc."""
    if isinstance(alias_data, dict):
        cmd = alias_data.get("command", "")
        desc = alias_data.get("description", "")
        suffix = f" - {desc}" if desc else ""
        return f"`{alias_name}` → `{cmd}`{suffix}"
    return f"`{alias_name}` → `{alias_data}`"


def format_standard_command_doc(cmd_name: str) -> str:
    """Format documentation for a standard system command."""
    doc = SYSTEM_COMMAND_DOCS.get(cmd_name)
    if not doc:
        return f"### {cmd_name}\nCommand: `{cmd_name} [options]`\n"

    lines = [f"### {cmd_name}", doc["description"], f"\n**Usage**: `{doc['usage']}`"]

    if "key_options" in doc:
        lines.append("\n**Key Options**:")
        for opt in doc["key_options"]:
            lines.append(f"- `{opt}`")

    if "key_filters" in doc:
        lines.append("\n**Key Filters**:")
        for filt in doc["key_filters"]:
            lines.append(f"- `{filt}`")

    if "examples" in doc:
        lines.append("\n**Examples**:")
        for example in doc["examples"]:
            lines.append(f"```bash\n{example}\n```")

    if "notes" in doc:
        lines.append(f"\n**Notes**: {doc['notes']}")

    return "\n".join(lines)


def _build_aliases_section() -> str:
    """Build the aliases section of command documentation."""
    from common.core.aliases import get_all_aliases

    aliases = get_all_aliases()
    if not aliases:
        return ""

    docs = ["## Aliases\n", "You can use these shortcuts instead of full commands:\n"]
    for alias_name, alias_data in sorted(aliases.items()):
        if isinstance(alias_data, dict):
            actual_cmd = alias_data.get("command", "")
            desc = alias_data.get("description", "")
        else:
            actual_cmd = alias_data
            desc = ""
        if desc:
            docs.append(f"- `{alias_name}` → `{actual_cmd}` - {desc}")
        else:
            docs.append(f"- `{alias_name}` → `{actual_cmd}`")
    docs.append("\nYou can use either the alias or the actual command.\n")
    docs.append("---\n")
    return "\n".join(docs)


def _build_fastmarket_tools_section(fastmarket_tools_config: dict) -> str:
    """Build the Fast-Market tools section of command documentation."""
    try:
        from common.core.aliases import get_reverse_aliases
    except ImportError:

        def get_reverse_aliases():
            return {}

    if not fastmarket_tools_config:
        return ""

    reverse_aliases = get_reverse_aliases()
    docs = ["## Fast-Market Tools\n"]

    for cmd, config in sorted(fastmarket_tools_config.items()):
        desc = config.get("description", "") if isinstance(config, dict) else ""
        if not desc:
            desc = f"{cmd} command-line tool"

        docs.append(f"### {cmd}")
        docs.append(desc)
        docs.append(f"**Usage**: `{cmd} [OPTIONS]`")

        if isinstance(config, dict) and config.get("commands"):
            commands = config["commands"]
            cmd_parts = []
            for c in commands:
                if isinstance(c, dict):
                    name, cdesc = next(iter(c.items()))
                    cmd_parts.append(f"`{name}` - {cdesc}")
                else:
                    cmd_parts.append(f"`{c}`")
            docs.append(f"**Commands**: {', '.join(cmd_parts)}")

        cmd_aliases = reverse_aliases.get(cmd, [])
        if cmd_aliases:
            docs.append(
                f"**Aliases**: {', '.join(f'`{a}`' for a in sorted(cmd_aliases))}"
            )
        docs.append("")

    return "\n".join(docs)


def _build_system_commands_section(system_commands: list[str]) -> str:
    """Build the system commands section of command documentation."""
    if not system_commands:
        return ""

    docs = ["\n## System Commands\n"]
    for cmd in sorted(system_commands):
        if cmd in SYSTEM_COMMAND_DOCS:
            docs.append(format_standard_command_doc(cmd))
        else:
            docs.append(
                f"### {cmd}\nCommand: `{cmd}` (run `{cmd} --help` for details)\n"
            )
        docs.append("")

    return "\n".join(docs)


def _load_task_config() -> dict:
    """Load task config from file, returning dict with task key."""
    from common.core.config import _resolve_config_path

    config_path = _resolve_config_path("task")
    if config_path.exists():
        import yaml

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        if "task" in data:
            return data
        return {"task": data}
    return {}


def _init_task_config(config: dict | None = None) -> dict:
    """Initialize task config with defaults if not present."""
    if config is None:
        config = _load_task_config()

    task = config.get("task", config)

    task.setdefault("fastmarket_tools", dict(DEFAULT_FASTMARKET_TOOLS))
    task.setdefault("system_commands", list(DEFAULT_SYSTEM_COMMANDS))

    if "agent_prompt" not in task:
        task["agent_prompt"] = {
            "active": "default",
            "templates": {
                "default": {
                    "description": "Default agent prompt",
                    "template": DEFAULT_AGENT_PROMPT_TEMPLATE,
                }
            },
        }

    if "command_docs" not in task:
        task["command_docs"] = {
            "active": "minimal",
            "templates": dict(DEFAULT_COMMAND_DOCS_TEMPLATES),
        }

    return task


def get_command_docs_prompt_config(command_docs_config: dict | None = None) -> dict:
    """Get the command docs prompt configuration.

    If command_docs_config is provided, use it directly. Otherwise, load from task config file.
    """
    if command_docs_config is not None:
        active_name = command_docs_config.get("active", "minimal")
        templates = command_docs_config.get("templates", {})
        template_config = templates.get(active_name, templates.get("minimal", {}))
        return {
            "name": active_name,
            "description": template_config.get("description", ""),
            "template": template_config.get("template", TOOLS_DOC_TEMPLATES["minimal"]),
        }

    config = _load_task_config()
    task = _init_task_config(config)
    command_docs = task.get("command_docs", {})
    active_name = command_docs.get("active", "minimal")
    templates = command_docs.get("templates", {})

    template_config = templates.get(active_name, templates.get("minimal", {}))
    return {
        "name": active_name,
        "description": template_config.get("description", ""),
        "template": template_config.get("template", TOOLS_DOC_TEMPLATES["minimal"]),
    }


def get_active_command_docs_prompt_config() -> dict:
    """Get the active command docs prompt configuration from task config."""
    return get_command_docs_prompt_config(None)


def get_active_agent_prompt_config() -> dict:
    """Get the active agent prompt configuration from task config file."""
    return get_agent_prompt_config(None)


def get_agent_prompt_config(agent_prompt_config: dict | None = None) -> dict:
    """Get the agent prompt configuration.

    If agent_prompt_config is provided, use it directly. Otherwise, load from task config file.
    """
    if agent_prompt_config is not None:
        active_name = agent_prompt_config.get("active", "default")
        templates = agent_prompt_config.get("templates", {})
        template_config = templates.get(active_name, templates.get("default", {}))
        return {
            "name": active_name,
            "description": template_config.get("description", ""),
            "template": template_config.get("template", DEFAULT_AGENT_PROMPT_TEMPLATE),
        }

    from common.prompt import get_cached_manager

    manager = get_cached_manager("task")
    if manager:
        template = manager.get("agent")
        if template:
            return {
                "name": "default",
                "description": "Default task execution prompt",
                "template": template,
            }

    config = _load_task_config()
    task = _init_task_config(config)
    agent_prompt = task.get("agent_prompt", {})
    active_name = agent_prompt.get("active", "default")
    templates = agent_prompt.get("templates", {})

    template_config = templates.get(active_name, templates.get("default", {}))

    return {
        "name": active_name,
        "description": template_config.get("description", ""),
        "template": template_config.get("template", DEFAULT_AGENT_PROMPT_TEMPLATE),
    }


def build_command_documentation(
    fastmarket_tools_config: dict,
    system_commands: list[str],
) -> dict[str, str]:
    """Build all command documentation placeholders.

    Args:
        fastmarket_tools_config: Dict of fastmarket tool configs {name: {description, commands}}
        system_commands: List of system command names

    Returns a dict with keys: aliases, fastmarket_tools, fastmarket_tools_minimal,
    fastmarket_tools_brief, fastmarket_tools_commands, system_commands,
    system_commands_minimal, other_commands, other_commands_minimal
    """
    aliases_section = _build_aliases_section()
    fastmarket_tools_section = _build_fastmarket_tools_section(fastmarket_tools_config)
    system_commands_section = _build_system_commands_section(system_commands)

    fastmarket_tools_minimal = ", ".join(
        f"`{c}`" for c in sorted(fastmarket_tools_config.keys())
    )
    if fastmarket_tools_minimal:
        fastmarket_tools_minimal = (
            f"**Fast-Market Tools**: {fastmarket_tools_minimal}\n"
        )

    fastmarket_tools_brief_parts = []
    for cmd in sorted(fastmarket_tools_config.keys()):
        config = fastmarket_tools_config[cmd]
        desc = config.get("description", "") if isinstance(config, dict) else ""
        if desc:
            fastmarket_tools_brief_parts.append(f"- `{cmd}` - {desc}")
        else:
            fastmarket_tools_brief_parts.append(f"- `{cmd}`")
    fastmarket_tools_brief = ""
    if fastmarket_tools_brief_parts:
        fastmarket_tools_brief = "\n".join(fastmarket_tools_brief_parts) + "\n"

    fastmarket_tools_commands_parts = []
    for cmd in sorted(fastmarket_tools_config.keys()):
        config = fastmarket_tools_config[cmd]
        if isinstance(config, dict) and config.get("commands"):
            cmd_parts = []
            for c in config["commands"]:
                if isinstance(c, dict):
                    name = next(iter(c.keys()))
                    cmd_parts.append(f"`{name}`")
                else:
                    cmd_parts.append(f"`{c}`")
            fastmarket_tools_commands_parts.append(f"- `{cmd}`: {', '.join(cmd_parts)}")
    fastmarket_tools_commands = ""
    if fastmarket_tools_commands_parts:
        fastmarket_tools_commands = (
            "**Fast-Market Commands**:\n"
            + "\n".join(fastmarket_tools_commands_parts)
            + "\n"
        )

    system_commands_minimal = _build_minimal_tools_section(
        system_commands, "**System Commands**"
    )

    from common.core.aliases import get_all_aliases

    aliases = get_all_aliases()
    aliases_minimal_parts = []
    for alias_name, alias_data in sorted(aliases.items()):
        aliases_minimal_parts.append(format_alias_minimal(alias_name, alias_data))
    aliases_minimal = ""
    if aliases_minimal_parts:
        aliases_minimal = "**Aliases**: " + ", ".join(aliases_minimal_parts) + "\n"

    other_commands = ""
    other_commands_minimal = ""

    return {
        "aliases": aliases_section,
        "fastmarket_tools": fastmarket_tools_section,
        "fastmarket_tools_minimal": fastmarket_tools_minimal,
        "fastmarket_tools_brief": fastmarket_tools_brief,
        "fastmarket_tools_commands": fastmarket_tools_commands,
        "system_commands": system_commands_section,
        "system_commands_minimal": system_commands_minimal,
        "other_commands": other_commands,
        "other_commands_minimal": other_commands_minimal,
    }


def render_command_documentation(
    fastmarket_tools_config: dict,
    system_commands: list[str],
    command_docs_config: dict | None = None,
) -> str:
    """Build formatted documentation using active template."""
    prompt_config = get_command_docs_prompt_config(command_docs_config)
    placeholders = build_command_documentation(fastmarket_tools_config, system_commands)
    return prompt_config["template"].format(**placeholders)


def build_system_prompt(
    task_description: str,
    fastmarket_tools_config: dict,
    system_commands: list[str],
    workdir: Path,
    task_params: dict[str, str] | None = None,
    command_docs_config: dict | None = None,
    agent_prompt_config: dict | None = None,
) -> str:
    """Build system prompt for task execution agent."""
    prompt_config = get_agent_prompt_config(agent_prompt_config)
    command_docs = render_command_documentation(
        fastmarket_tools_config, system_commands, command_docs_config
    )

    params_section = ""
    env_vars_section = ""
    if task_params:
        params_section = "\n# Task Parameters (Already Resolved)\n"
        for key, value in sorted(task_params.items()):
            display_value = value if len(value) < 200 else value[:197] + "..."
            params_section += f"- **{key}**: {display_value}\n"

        env_vars_section = "# Environment Variables\n"
        env_vars_section += "Task parameters are available as environment variables in shell commands.\n"
        env_vars_section += (
            "Parameter names are CAPITALIZED and prefixed with `SKILL_`.\n"
        )
        env_vars_section += (
            "For example, parameter `message` becomes `$SKILL_MESSAGE`.\n"
        )
        env_vars_section += "\nAvailable environment variables:\n"
        for key in sorted(task_params.keys()):
            env_vars_section += (
                f"- `$SKILL_{str(key).upper()}` (from parameter `{key}`)\n"
            )
        env_vars_section += "\n"

    template = prompt_config.get("template", DEFAULT_AGENT_PROMPT_TEMPLATE)
    return template.format(
        task_description=task_description,
        params_section=params_section,
        env_vars_section=env_vars_section,
        workdir=str(workdir),
        command_docs=command_docs,
    )
