"""Prompt processor for batch-comment-reply command.

Supports:
- @filename syntax to include file contents
- @- to read from stdin
- Template variables like {URL}, {AUTHOR}, {VIDEO_URL}, etc.
- Multiple prompts concatenated with proper separation
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


# Pattern to match @filename or @- references
FILE_REF_PATTERN = re.compile(r"@([^\s]+)")

# Common template variables that can be used in prompts
TEMPLATE_VARS = {
    "{URL}",
    "{VIDEO_URL}",
    "{VIDEO_ID}",
    "{AUTHOR}",
    "{COMMENT}",
    "{COMMENT_TEXT}",
    "{VIDEO_TITLE}",
}


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


def apply_template_variables(prompt: str, data: dict[str, Any]) -> str:
    """Replace template variables with actual values from data.

    Supported variables:
    - {URL} or {VIDEO_URL} -> data.get('video_url', '')
    - {VIDEO_ID} -> data.get('video_id', '')
    - {AUTHOR} or {COMMENT_AUTHOR} -> data.get('author', '')
    - {COMMENT} or {COMMENT_TEXT} -> data.get('text', '')
    - {VIDEO_TITLE} -> data.get('video_title', '')

    Args:
        prompt: The prompt text with template variables
        data: Dictionary containing the actual values

    Returns:
        Prompt with template variables replaced
    """
    # Map of template variables to data keys
    var_mapping = {
        "{URL}": "video_url",
        "{VIDEO_URL}": "video_url",
        "{VIDEO_ID}": "video_id",
        "{AUTHOR}": "author",
        "{COMMENT_AUTHOR}": "author",
        "{COMMENT}": "text",
        "{COMMENT_TEXT}": "text",
        "{VIDEO_TITLE}": "video_title",
    }

    result = prompt
    for template_var, data_key in var_mapping.items():
        if template_var in result:
            value = str(data.get(data_key, ""))
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
