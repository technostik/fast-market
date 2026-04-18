from commands.batch_comment_reply.prompt_processor import (
    apply_template_variables as _apply_template_variables,
    process_prompts as _process_prompts,
    resolve_file_references,
    PromptProcessorError,
)

from pathlib import Path
from typing import Any


TEMPLATE_VARS = {
    "{URL}",
    "{VIDEO_URL}",
    "{VIDEO_ID}",
    "{VIDEO_TITLE}",
    "{VIDEO_DESCRIPTION}",
    "{CHANNEL_NAME}",
    "{CHANNEL_ID}",
    "{TRANSCRIPT}",
    "{PUBLISHED_AT}",
}


def apply_template_variables(prompt: str, data: dict[str, Any]) -> str:
    var_mapping = {
        "{URL}": "url",
        "{VIDEO_URL}": "url",
        "{VIDEO_ID}": "video_id",
        "{VIDEO_TITLE}": "title",
        "{VIDEO_DESCRIPTION}": "description",
        "{CHANNEL_NAME}": "channel_name",
        "{CHANNEL_ID}": "channel_id",
        "{TRANSCRIPT}": "transcript",
        "{PUBLISHED_AT}": "published_at",
    }

    result = prompt
    for template_var, data_key in var_mapping.items():
        if template_var in result:
            value = str(data.get(data_key, ""))
            result = result.replace(template_var, value)

    result = _apply_template_variables(result, data)

    return result


def process_prompts(
    prompts: list[str],
    data: dict[str, Any],
    working_dir: Path | None = None,
) -> str:
    if not prompts:
        raise PromptProcessorError("No prompts provided")

    separator = "\n\n---\n\n"
    combined_prompt = separator.join(prompts)

    resolved_prompt = resolve_file_references(combined_prompt, working_dir)

    final_prompt = apply_template_variables(resolved_prompt, data)

    return final_prompt
