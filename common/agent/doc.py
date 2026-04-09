"""
Multi-level tool documentation builder for agent prompts.

Dynamically discovers tool documentation by calling --help on each tool
and building structured markdown at different depth levels.
"""
from __future__ import annotations

import subprocess
from typing import Any

# Safety limit for recursive discovery
MAX_RECURSION_DEPTH = 8


def _run_help(tool: str, args: list[str] | None = None, timeout: int = 5) -> str | None:
    """Run a tool with --help and return output, or None on failure."""
    try:
        cmd = [tool]
        if args:
            cmd.extend(args)
        cmd.append("--help")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (result.stdout or result.stderr).strip() or None
    except Exception:
        return None


def _parse_help_output(output: str, tool_name: str) -> dict[str, Any]:
    """Parse --help output into structured data.
    
    Returns dict with:
    - name: tool name
    - description: short description
    - commands: list of subcommands (if any)
    """
    if not output:
        return {
            "name": tool_name,
            "description": f"Project CLI: `{tool_name}`.",
            "commands": [],
        }
    
    lines = output.split("\n")
    
    # Extract description (usually first line or after tool name)
    description = lines[0] if lines else f"Project CLI: `{tool_name}`."
    if len(description) > 120:
        description = description[:120] + "..."
    
    # Extract commands section
    commands = []
    in_commands = False
    
    for line in lines:
        stripped = line.strip()
        
        # Detect commands section
        if stripped.lower().startswith("commands"):
            in_commands = True
            continue
        
        # End of commands section
        if in_commands and (
            stripped.startswith("-") or 
            stripped.startswith("Options") or
            stripped.startswith("Arguments") or
            (stripped == "" and len(commands) > 0)
        ):
            # Skip empty lines after we've found commands
            if stripped == "":
                continue
            break
        
        # Parse command lines
        if in_commands and stripped:
            # Command format: "  name  description" or "name  description"
            parts = stripped.split(None, 1)
            if parts:
                cmd_name = parts[0].rstrip(",")
                cmd_desc = parts[1].strip() if len(parts) > 1 else ""
                
                # Skip meta-commands
                if cmd_name not in ("setup", "serve", "status", "stats", "embed-server",
                                    "batch-comments", "batch-post", "batch-reply"):
                    commands.append({
                        "name": cmd_name,
                        "description": cmd_desc,
                        "subcommands": [],
                    })
    
    return {
        "name": tool_name,
        "description": description,
        "commands": commands,
    }


def _get_subcommands(tool_name: str, parent_path: list[str], current_depth: int, max_depth: int) -> list[dict[str, Any]]:
    """Recursively get subcommands for a command path."""
    if current_depth >= max_depth:
        return []
    
    # Build command path
    cmd_path = [tool_name] + parent_path
    help_output = _run_help(cmd_path[0], cmd_path[1:])
    
    if not help_output:
        return []
    
    parsed = _parse_help_output(help_output, cmd_path[-1])
    return parsed.get("commands", [])


def _format_tool_doc(tool_info: dict[str, Any], depth: int, current_depth: int = 1, indent: str = "") -> str:
    """Format tool information as markdown documentation."""
    lines = []
    
    # Level 1: Tool name + description only
    if depth == 1:
        lines.append(f"{indent}- `{tool_info['name']}` — {tool_info['description']}")
    
    # Level 2+: Include first-level subcommands
    elif depth == 2:
        lines.append(f"{indent}- `{tool_info['name']}` — {tool_info['description']}")
        if tool_info.get("commands"):
            for cmd in tool_info["commands"]:
                lines.append(f"{indent}  - `{tool_info['name']} {cmd['name']}` — {cmd['description']}")
    
    # Level 3+: Include sub-subcommands
    elif depth == 3:
        lines.append(f"{indent}- `{tool_info['name']}` — {tool_info['description']}")
        if tool_info.get("commands"):
            for cmd in tool_info["commands"]:
                lines.append(f"{indent}  - `{tool_info['name']} {cmd['name']}` — {cmd['description']}")
                if cmd.get("subcommands"):
                    for subcmd in cmd["subcommands"]:
                        lines.append(f"{indent}    - `{tool_info['name']} {cmd['name']} {subcmd['name']}` — {subcmd['description']}")
    
    # Level 0: Recursive until no more subcommands
    elif depth == 0:
        lines.append(f"{indent}- `{tool_info['name']}` — {tool_info['description']}")
        if tool_info.get("commands"):
            _format_commands_recursive(lines, tool_info["commands"], tool_info["name"], current_depth=1, max_depth=MAX_RECURSION_DEPTH, indent=indent)
    
    return "\n".join(lines)


def _format_commands_recursive(
    lines: list[str], 
    commands: list[dict[str, Any]], 
    tool_name: str, 
    current_depth: int, 
    max_depth: int,
    indent: str = "",
) -> None:
    """Recursively format commands with subcommands."""
    if current_depth >= max_depth or not commands:
        return
    
    indent_level = "  " * (current_depth + 1)
    full_prefix = f"{tool_name} "
    
    for cmd in commands:
        cmd_path = f"{full_prefix}{cmd['name']}"
        lines.append(f"{indent}{indent_level}- `{cmd_path}` — {cmd['description']}")
        
        # Recurse into subcommands
        if cmd.get("subcommands"):
            # Get subcommands by calling tool --help
            subcommands = _get_subcommands(
                tool_name, 
                [c["name"] for c in commands[:commands.index(cmd)]], 
                current_depth, 
                max_depth
            )
            if subcommands:
                cmd["subcommands"] = subcommands
                _format_commands_recursive(
                    lines, 
                    cmd["subcommands"], 
                    f"{tool_name} {cmd['name']}", 
                    current_depth + 1, 
                    max_depth,
                    indent
                )


def build_tool_documentation(
    tools: list[str] | None = None,
    depth: int = 1,
    include_system_commands: bool = True,
    system_commands: list[str] | None = None,
) -> str:
    """Build multi-level tool documentation as formatted markdown.
    
    Args:
        tools: List of tool names to document. Uses DEFAULT_FASTMARKET_TOOLS if None.
        depth: Documentation depth level:
            - 1: Tool name + description only
            - 2: Level 1 + first-level subcommands
            - 3: Level 2 + sub-subcommands and options
            - 0: Recursive discovery until no more subcommands (max depth 8)
        include_system_commands: Whether to include standard shell utilities.
        system_commands: List of system commands to include.
    
    Returns:
        Formatted markdown string suitable for agent prompts.
    """
    from common.agent.executor import DEFAULT_FASTMARKET_TOOLS
    
    tool_list = tools or sorted(DEFAULT_FASTMARKET_TOOLS)
    lines = ["# Available Tools", ""]
    
    # Fast-Market tools section
    if tool_list:
        lines.append("## Fast-Market Tools")
        lines.append("These are project-specific CLIs. Discover subcommands with `tool --help`.")
        lines.append("")
        
        for tool_name in sorted(tool_list):
            # Get tool documentation
            help_output = _run_help(tool_name)
            tool_info = _parse_help_output(help_output, tool_name)
            
            # For depth 3+, get subcommands
            if depth >= 3:
                subcommands = _get_subcommands(tool_name, [], 0, max(2, depth))
                if subcommands:
                    tool_info["commands"] = subcommands
            
            # Format and add
            doc = _format_tool_doc(tool_info, depth)
            lines.append(doc)
        
        lines.append("")
    
    # System commands section
    if include_system_commands:
        sys_cmds = system_commands or [
            "ls", "cat", "head", "tail", "grep", "find", "wc",
            "mkdir", "touch", "cp", "mv", "rm", "chmod", "date",
            "printf", "sed", "awk", "cut", "tr", "sort", "uniq",
            "curl", "wget", "jq", "tee", "tar", "gzip", "zip", "unzip",
        ]
        
        lines.append("## System Commands")
        lines.append("Standard shell utilities. Use `tool --help` for options.")
        lines.append("")
        lines.append(", ".join(f"`{c}`" for c in sorted(sys_cmds)))
        lines.append("")
    
    # Discovery instructions
    lines.append("## Discovery")
    lines.append("- Use `tool --help` at runtime to discover flags and options")
    lines.append("- Use `command -v tool` to check if a tool is available")
    lines.append("- Include fallback logic when tools may be missing")
    lines.append("")
    
    return "\n".join(lines)
