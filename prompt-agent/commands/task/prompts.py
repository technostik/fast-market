from __future__ import annotations

from pathlib import Path

from core.task_prompt import TaskPromptConfig, DEFAULT_PROMPT_TEMPLATE
from common.core.paths import get_skills_dir
from core.skill import discover_skills


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

DEFAULT_TOOLS_DOC_TEMPLATE = (
    """{aliases}{fastmarket_tools}{system_commands}{other_commands}{skills}"""
)


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


def _build_fastmarket_tools_section(allowed_commands: list[str]) -> str:
    """Build the Fast-Market tools section of command documentation."""
    from commands.task.command_registry import get_fastmarket_command_help
    from common.core.aliases import get_reverse_aliases

    fastmarket_cmds = {"corpus", "youtube", "image", "message", "prompt"}
    fm_allowed = [c for c in allowed_commands if c in fastmarket_cmds]
    if not fm_allowed:
        return ""

    reverse_aliases = get_reverse_aliases()
    docs = ["## Fast-Market Tools\n"]

    for cmd in sorted(fm_allowed):
        info = get_fastmarket_command_help(cmd)
        if info is None:
            docs.append(f"### {cmd}")
            docs.append(f"{cmd} command-line tool")
            docs.append(f"**Usage**: `{cmd} [OPTIONS]`")
        else:
            docs.append(f"### {info.name}")
            docs.append(info.description)
            docs.append(f"**Usage**: `{info.usage}`")
        cmd_aliases = reverse_aliases.get(cmd, [])
        if cmd_aliases:
            docs.append(
                f"**Aliases**: {', '.join(f'`{a}`' for a in sorted(cmd_aliases))}"
            )
        if info and info.examples:
            docs.append("\n**Quick Examples**:")
            for ex in info.examples:
                docs.append(f"- `{ex}`")
        docs.append("")

    return "\n".join(docs)


def _build_system_commands_section(allowed_commands: list[str]) -> str:
    """Build the system commands section of command documentation."""
    system_cmds = set(SYSTEM_COMMAND_DOCS.keys())
    sys_allowed = [c for c in allowed_commands if c in system_cmds]
    if not sys_allowed:
        return ""

    docs = ["\n## System Commands\n"]
    for cmd in sorted(sys_allowed):
        docs.append(format_standard_command_doc(cmd))
        docs.append("")

    return "\n".join(docs)


def _build_other_commands_section(allowed_commands: list[str]) -> str:
    """Build the other commands section of command documentation."""
    from common.core.aliases import get_reverse_aliases

    fastmarket_cmds = {"corpus", "youtube", "image", "message", "prompt"}
    system_cmds = set(SYSTEM_COMMAND_DOCS.keys())
    other_allowed = [
        c for c in allowed_commands if c not in fastmarket_cmds and c not in system_cmds
    ]
    if not other_allowed:
        return ""

    reverse_aliases = get_reverse_aliases()
    docs = ["\n## Other Commands\n"]

    for cmd in sorted(other_allowed):
        docs.append(f"### {cmd}")
        docs.append(f"Command: `{cmd}` (run `{cmd} --help` for details)")
        cmd_aliases = reverse_aliases.get(cmd, [])
        if cmd_aliases:
            docs.append(
                f"**Aliases**: {', '.join(f'`{a}`' for a in sorted(cmd_aliases))}"
            )
        docs.append("")

    return "\n".join(docs)


def _build_skills_section() -> str:
    """Build the skills section of command documentation."""
    skills_dir = get_skills_dir()
    skills = discover_skills(skills_dir)
    if not skills:
        return ""

    docs = ["\n## Skills\n"]
    docs.append(
        "Skills provide specialized capabilities for specific tasks. Use `skill:name/script [args]` to execute.\n"
    )

    for skill in skills:
        docs.append(f"### {skill.name}")
        if skill.description:
            docs.append(f"{skill.description}")
        if skill.has_scripts:
            scripts_dir = skill.path / "scripts"
            scripts = [
                f.name
                for f in scripts_dir.iterdir()
                if f.is_file() and not f.name.startswith(".")
            ]
            if scripts:
                docs.append(
                    f"**Scripts**: {', '.join(f'`{s}`' for s in sorted(scripts))}"
                )
        docs.append("")

    return "\n".join(docs)


def get_active_tools_doc_prompt_config() -> TaskPromptConfig:
    """Get the active tools doc prompt configuration."""
    from common.core.config import load_tool_config
    from common.core.paths import get_fastmarket_dir

    config = load_tool_config("prompt")
    active_tools_doc = config.get("tools_doc_prompt", "default")

    if active_tools_doc == "default":
        return TaskPromptConfig(
            name="default",
            description="Default tools documentation",
            template=DEFAULT_TOOLS_DOC_TEMPLATE,
        )

    tools_doc_path = (
        get_fastmarket_dir() / "tools_doc_prompts" / f"{active_tools_doc}.yaml"
    )
    prompt_config = TaskPromptConfig.from_yaml(tools_doc_path)
    if not prompt_config:
        return TaskPromptConfig(
            name="default",
            description="Default tools documentation",
            template=DEFAULT_TOOLS_DOC_TEMPLATE,
        )

    return prompt_config


def build_command_documentation(allowed_commands: list[str]) -> str:
    """Build formatted documentation for all allowed commands using template."""
    aliases_section = _build_aliases_section()
    fastmarket_tools_section = _build_fastmarket_tools_section(allowed_commands)
    system_commands_section = _build_system_commands_section(allowed_commands)
    other_commands_section = _build_other_commands_section(allowed_commands)
    skills_section = _build_skills_section()

    if not any(
        [
            aliases_section,
            fastmarket_tools_section,
            system_commands_section,
            other_commands_section,
            skills_section,
        ]
    ):
        return ""

    prompt_config = get_active_tools_doc_prompt_config()

    return prompt_config.render(
        aliases=aliases_section,
        fastmarket_tools=fastmarket_tools_section,
        system_commands=system_commands_section,
        other_commands=other_commands_section,
        skills=skills_section,
    )


def build_system_prompt(
    task_description: str,
    allowed_commands: list[str],
    workdir: Path,
    task_params: dict[str, str] | None = None,
) -> str:
    """Build system prompt for task execution agent."""
    command_docs = build_command_documentation(allowed_commands)

    params_section = ""
    if task_params:
        params_section = "\n# Task Parameters (Already Resolved)\n"
        for key, value in sorted(task_params.items()):
            display_value = value if len(value) < 200 else value[:197] + "..."
            params_section += f"- **{key}**: {display_value}\n"

    return f"""You are a task execution agent. You have access to a sandboxed command-line environment to accomplish tasks.

# Your Task
{task_description}
{params_section}

# Working Directory
All commands execute in: `{workdir}`

You can read and write files in this directory. Relative paths are resolved from here.

---

{command_docs}

---

# How to Work

1. **Understand the task**: Break it down into clear steps
2. **Explore first**: Use `ls` and `cat` to understand what files exist
3. **Execute incrementally**: Run one command, check the result, then decide next step
4. **Handle errors**: If a command fails, read the error message and try a different approach
5. **Stay focused**: Only use commands that advance the task
6. **Finish clearly**: When done, summarize what you accomplished (without making tool calls)

# Critical Rules

- **Only use listed commands** - others will be rejected
- **Work within the directory** - you cannot escape `{workdir}`
- **Check outputs** - always verify command results before proceeding
- **Be efficient** - prefer one good command over many guesses
- **Ask for help** - if truly stuck, explain what you need

"""


def get_active_prompt_config() -> TaskPromptConfig:
    """Get the active prompt configuration."""
    from common.core.config import load_tool_config
    from common.core.paths import get_fastmarket_dir

    config = load_tool_config("prompt")
    active_prompt = config.get("task", {}).get("active_prompt", "default")

    if active_prompt == "default":
        return TaskPromptConfig(
            name="default",
            description="Default task execution prompt",
            template=DEFAULT_PROMPT_TEMPLATE,
        )

    prompt_path = get_fastmarket_dir() / "task_prompts" / f"{active_prompt}.yaml"
    prompt_config = TaskPromptConfig.from_yaml(prompt_path)
    if not prompt_config:
        return TaskPromptConfig(
            name="default",
            description="Default task execution prompt",
            template=DEFAULT_PROMPT_TEMPLATE,
        )

    return prompt_config


def build_system_prompt(
    task_description: str,
    allowed_commands: list[str],
    workdir: Path,
    task_params: dict[str, str] | None = None,
) -> str:
    """Build system prompt for task execution agent."""
    prompt_config = get_active_prompt_config()
    command_docs = build_command_documentation(allowed_commands)

    params_section = ""
    if task_params:
        params_section = "\n# Task Parameters (Already Resolved)\n"
        for key, value in sorted(task_params.items()):
            display_value = value if len(value) < 200 else value[:197] + "..."
            params_section += f"- **{key}**: {display_value}\n"

    return prompt_config.render(
        task_description=task_description,
        params_section=params_section,
        workdir=str(workdir),
        command_docs=command_docs,
    )
