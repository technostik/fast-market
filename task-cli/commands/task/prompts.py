from __future__ import annotations
from common.agent.prompts import (
    DEFAULT_AGENT_PROMPT_TEMPLATE,
    DEFAULT_FASTMARKET_TOOLS,
    DEFAULT_SYSTEM_COMMANDS,
    SYSTEM_COMMAND_DOCS,
    TOOLS_DOC_TEMPLATES,
    build_system_prompt,
    render_command_documentation,
    build_command_documentation,
    get_active_agent_prompt_config,
    get_active_command_docs_prompt_config,
    format_standard_command_doc,
    _build_aliases_section,
    _build_fastmarket_tools_section,
    _build_system_commands_section,
    _build_minimal_tools_section,
)

__all__ = [
    "DEFAULT_AGENT_PROMPT_TEMPLATE",
    "DEFAULT_FASTMARKET_TOOLS",
    "DEFAULT_SYSTEM_COMMANDS",
    "SYSTEM_COMMAND_DOCS",
    "TOOLS_DOC_TEMPLATES",
    "build_system_prompt",
    "render_command_documentation",
    "build_command_documentation",
    "get_active_agent_prompt_config",
    "get_active_command_docs_prompt_config",
]

# Backward compatibility alias
get_active_tools_doc_prompt_config = get_active_command_docs_prompt_config
