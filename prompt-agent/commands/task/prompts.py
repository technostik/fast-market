from __future__ import annotations

from pathlib import Path


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


def build_command_documentation(allowed_commands: list[str]) -> str:
    """Build formatted documentation for all allowed commands."""
    from commands.task.command_registry import get_fastmarket_command_help

    fastmarket_cmds = {"corpus", "youtube", "image", "message", "prompt"}
    system_cmds = set(SYSTEM_COMMAND_DOCS.keys())

    docs = ["# Available Commands\n"]

    fm_allowed = [c for c in allowed_commands if c in fastmarket_cmds]
    sys_allowed = [c for c in allowed_commands if c in system_cmds]
    other_allowed = [
        c for c in allowed_commands if c not in fastmarket_cmds and c not in system_cmds
    ]

    if fm_allowed:
        docs.append("## Fast-Market Tools\n")
        for cmd in sorted(fm_allowed):
            info = get_fastmarket_command_help(cmd)
            if info:
                docs.append(f"### {info.name}")
                docs.append(info.description)
                docs.append(f"**Usage**: `{info.usage}`")
                if info.examples:
                    docs.append("\n**Quick Examples**:")
                    for ex in info.examples:
                        docs.append(f"- `{ex}`")
                docs.append("")

    if sys_allowed:
        docs.append("\n## System Commands\n")
        for cmd in sorted(sys_allowed):
            docs.append(format_standard_command_doc(cmd))
            docs.append("")

    if other_allowed:
        docs.append("\n## Other Commands\n")
        for cmd in sorted(other_allowed):
            docs.append(f"### {cmd}")
            docs.append(f"Command: `{cmd}` (run `{cmd} --help` for details)")
            docs.append("")

    return "\n".join(docs)


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

# Tool Usage

Use the `execute_command` tool to run commands. Provide:
- `command`: The full command string (e.g., "corpus search 'AI' --limit 5")
- `explanation`: Brief reason for running this command

Example:
```json
{{
  "command": "ls -la",
  "explanation": "Check what files are in the working directory"
}}
```

# When You're Done

Respond with a natural language summary of what you accomplished. Do NOT make any more tool calls when the task is complete.

Example completion:
"I've completed the task. I searched the corpus for 'AI safety' topics, found 5 relevant documents, and created a summary in summary.md with key points and examples from each source."
"""
