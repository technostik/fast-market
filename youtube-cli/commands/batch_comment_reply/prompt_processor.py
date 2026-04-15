"""Prompt processor for batch-comment-reply command.

Supports:
- @filename syntax to include file contents
- @- to read from stdin
- Template variables like {URL}, {AUTHOR}, {VIDEO_URL}, etc.
- Multiple prompts concatenated with proper separation
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


# Pattern to match @filename or @- references
FILE_REF_PATTERN = re.compile(r"@([^\s]+)")


class PromptProcessorError(Exception):
    """Error during prompt processing."""

    pass


def read_file_content(file_ref: str, working_dir: Path | None = None) -> str:
    """Read content from a file reference.

    Args:
        file_ref: The filename or '-' for stdin
        working_dir: Base directory for resolving relative paths

    Returns:
        The file contents as a string

    Raises:
        PromptProcessorError: If file cannot be read
    """
    if file_ref == "-":
        # Read from stdin
        try:
            content = sys.stdin.read()
            if not content:
                raise PromptProcessorError("No data received from stdin")
            return content
        except Exception as e:
            raise PromptProcessorError(f"Failed to read from stdin: {e}")

    # Resolve file path
    file_path = Path(file_ref)
    if not file_path.is_absolute():
        if working_dir:
            file_path = working_dir / file_path
        else:
            file_path = Path.cwd() / file_path

    if not file_path.exists():
        raise PromptProcessorError(f"File not found: {file_path}")

    if not file_path.is_file():
        raise PromptProcessorError(f"Not a file: {file_path}")

    try:
        return file_path.read_text(encoding="utf-8")
    except Exception as e:
        raise PromptProcessorError(f"Failed to read file '{file_path}': {e}")


def resolve_file_references(prompt: str, working_dir: Path | None = None) -> str:
    """Replace @filename references with actual file contents.

    Args:
        prompt: The prompt text potentially containing @file references
        working_dir: Base directory for resolving relative paths

    Returns:
        Prompt with file references replaced by file contents
    """

    def replace_ref(match):
        file_ref = match.group(1)
        try:
            content = read_file_content(file_ref, working_dir)
            return content
        except PromptProcessorError as e:
            # Re-raise with context
            raise PromptProcessorError(f"Error resolving '{match.group(0)}': {e}")

    return FILE_REF_PATTERN.sub(replace_ref, prompt)


def _sanitize_key(key: str) -> str:
    """Convert a key to uppercase env var format with underscores."""
    sanitized = key.upper()
    sanitized = re.sub(r"[^A-Z0-9_]", "_", sanitized)
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized.strip("_")


def _flatten_dict(
    data: dict[str, Any], parent_key: str = "", sep: str = "_"
) -> dict[str, str]:
    """Flatten a nested dictionary into dot-notation keys."""
    items = {}
    for key, value in data.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict):
            items.update(_flatten_dict(value, new_key, sep))
        elif isinstance(value, list):
            items[new_key] = json.dumps(value)
        else:
            items[new_key] = str(value) if value is not None else ""
    return items


def apply_template_variables(prompt: str, data: dict[str, Any]) -> str:
    """Replace template variables with actual values from data.

    Supports ALL fields from input data as template variables:
    - Matches {FIELD_NAME} to data['field_name'] (case-insensitive key match)
    - Also supports dot notation: {author.name} -> data['author']['name']
    - Falls back to common aliases for backward compatibility

    Args:
        prompt: The prompt text with template variables
        data: Dictionary containing the actual values

    Returns:
        Prompt with template variables replaced
    """
    flattened = _flatten_dict(data)
    result = prompt

    for template_var in re.findall(r"\{[^}]+\}", result):
        key = template_var[1:-1]
        value = None

        if key in data:
            val = data[key]
            value = str(val) if val is not None else ""
        elif key in flattened:
            value = flattened[key]
        else:
            lower_key = key.lower()
            for data_key, data_val in data.items():
                if data_key.lower() == lower_key:
                    value = str(data_val) if data_val is not None else ""
                    break

        if value is not None:
            result = result.replace(template_var, value)

    return result


def process_prompts(
    prompts: list[str],
    data: dict[str, Any],
    working_dir: Path | None = None,
) -> str:
    """Process multiple prompts into a single prompt string.

    This function:
    1. Concatenates multiple prompts with proper separation
    2. Resolves @file references (including @- for stdin)
    3. Applies template variable substitution

    Args:
        prompts: List of prompt strings (from multiple -p flags)
        data: Dictionary containing values for template variables
        working_dir: Base directory for resolving relative file paths

    Returns:
        Final processed prompt string

    Raises:
        PromptProcessorError: If processing fails
    """
    if not prompts:
        raise PromptProcessorError("No prompts provided")

    # Step 1: Concatenate multiple prompts with separator
    separator = "\n\n---\n\n"
    combined_prompt = separator.join(prompts)

    # Step 2: Resolve file references
    resolved_prompt = resolve_file_references(combined_prompt, working_dir)

    # Step 3: Apply template variables
    final_prompt = apply_template_variables(resolved_prompt, data)

    return final_prompt
