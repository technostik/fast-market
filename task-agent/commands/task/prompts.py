from __future__ import annotations

from pathlib import Path

from common.core.paths import get_skills_dir
from common.skill.skill import discover_skills


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
    "full": "{aliases}{fastmarket_tools}{system_commands}{other_commands}{skills}",
    "minimal": "{aliases}{fastmarket_tools_minimal}{system_commands_minimal}{other_commands_minimal}{skills_minimal}",
}


def _build_minimal_tools_section(commands: list[str], section_name: str) -> str:
    """Build minimal section with just command names."""
    if not commands:
        return ""
    names = ", ".join(f"`{c}`" for c in sorted(commands))
    return f"{section_name}: {names}\n"


def format_fastmarket_tool_minimal(cmd_name: str) -> str:
    """Format minimal fastmarket tool doc."""
    from commands.task.command_registry import get_fastmarket_command_help

    info = get_fastmarket_command_help(cmd_name)
    if info:
        return f"`{info.name}`"
    return f"`{cmd_name}`"


def format_other_command_minimal(cmd_name: str) -> str:
    """Format minimal other command doc."""
    return f"`{cmd_name}`"


def format_skill_minimal(skill) -> str:
    """Format minimal skill doc."""
    return f"`skill:{skill.name}/script`"


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
    from commands.task.command_registry import get_fastmarket_command_help
    from common.core.aliases import get_reverse_aliases

    if not fastmarket_tools_config:
        return ""

    reverse_aliases = get_reverse_aliases()
    docs = ["## Fast-Market Tools\n"]

    for cmd, config in sorted(fastmarket_tools_config.items()):
        info = get_fastmarket_command_help(cmd)
        desc = config.get("description", "") if isinstance(config, dict) else ""
        if info and not desc:
            desc = info.description
        if not desc:
            desc = f"{cmd} command-line tool"

        docs.append(f"### {cmd}")
        docs.append(desc)
        docs.append(f"**Usage**: `{cmd} [OPTIONS]`")

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


def get_active_tools_doc_prompt_config() -> dict:
    """Get the active tools doc prompt configuration from task config."""
    from common.core.config import load_tool_config
    from commands.setup import init_task_config

    config = load_tool_config("task")
    task = init_task_config(config)
    tools_doc = task.get("tools_doc", {})
    active_name = tools_doc.get("active", "minimal")
    templates = tools_doc.get("templates", {})

    template_config = templates.get(active_name, templates.get("minimal", {}))
    return {
        "name": active_name,
        "description": template_config.get("description", ""),
        "template": template_config.get("template", TOOLS_DOC_TEMPLATES["minimal"]),
    }


def get_active_agent_prompt_config() -> dict:
    """Get the active agent prompt configuration from task config."""
    from common.core.config import load_tool_config
    from commands.setup import init_task_config

    config = load_tool_config("task")
    task = init_task_config(config)
    agent_prompt = task.get("agent_prompt", {})
    active_name = agent_prompt.get("active", "default")
    templates = agent_prompt.get("templates", {})

    template_config = templates.get(active_name, templates.get("default", {}))
    from commands.setup import DEFAULT_AGENT_PROMPT_TEMPLATE

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
    system_commands_minimal, skills, skills_minimal
    """
    aliases_section = _build_aliases_section()
    fastmarket_tools_section = _build_fastmarket_tools_section(fastmarket_tools_config)
    system_commands_section = _build_system_commands_section(system_commands)
    skills_section = _build_skills_section()

    skills_dir = get_skills_dir()
    skills = discover_skills(skills_dir)

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
            cmds_list = ", ".join(f"`{c}`" for c in config["commands"])
            fastmarket_tools_commands_parts.append(f"- `{cmd}`: {cmds_list}")
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

    skills_minimal_parts = []
    for skill in skills:
        if skill.has_scripts:
            scripts_dir = skill.path / "scripts"
            scripts = [
                f.name
                for f in scripts_dir.iterdir()
                if f.is_file() and not f.name.startswith(".")
            ]
            for script in sorted(scripts):
                skills_minimal_parts.append(f"skill:{skill.name}/{script}")
    skills_minimal = ""
    if skills_minimal_parts:
        skills_minimal = (
            "**Skills**: " + ", ".join(f"`{s}`" for s in skills_minimal_parts) + "\n"
        )

    return {
        "aliases": aliases_section,
        "fastmarket_tools": fastmarket_tools_section,
        "fastmarket_tools_minimal": fastmarket_tools_minimal,
        "fastmarket_tools_brief": fastmarket_tools_brief,
        "fastmarket_tools_commands": fastmarket_tools_commands,
        "system_commands": system_commands_section,
        "system_commands_minimal": system_commands_minimal,
        "skills": skills_section,
        "skills_minimal": skills_minimal,
    }


def render_command_documentation(
    fastmarket_tools_config: dict,
    system_commands: list[str],
) -> str:
    """Build formatted documentation using active template."""
    prompt_config = get_active_tools_doc_prompt_config()
    placeholders = build_command_documentation(fastmarket_tools_config, system_commands)
    return prompt_config["template"].format(**placeholders)


def build_system_prompt(
    task_description: str,
    fastmarket_tools_config: dict,
    system_commands: list[str],
    workdir: Path,
    task_params: dict[str, str] | None = None,
) -> str:
    """Build system prompt for task execution agent."""
    from commands.setup import DEFAULT_AGENT_PROMPT_TEMPLATE

    prompt_config = get_active_agent_prompt_config()
    command_docs = render_command_documentation(
        fastmarket_tools_config, system_commands
    )

    params_section = ""
    if task_params:
        params_section = "\n# Task Parameters (Already Resolved)\n"
        for key, value in sorted(task_params.items()):
            display_value = value if len(value) < 200 else value[:197] + "..."
            params_section += f"- **{key}**: {display_value}\n"

    template = prompt_config.get("template", DEFAULT_AGENT_PROMPT_TEMPLATE)
    return template.format(
        task_description=task_description,
        params_section=params_section,
        workdir=str(workdir),
        command_docs=command_docs,
    )
