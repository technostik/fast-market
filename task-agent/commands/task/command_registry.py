from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from common import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CommandInfo:
    """Documentation for a whitelisted command."""

    name: str
    description: str
    usage: str
    examples: list[str]


_COMMAND_MODULES = {
    "corpus": "corpus_agent",
    "image": "image_agent",
    "youtube": "youtube_agent",
    "message": "message_agent",
    "prompt": "prompt_agent",
}

_COMMAND_ENTRY_POINTS = {
    "corpus": ("corpus", "corpus-agent/corpus_entry"),
    "image": ("image", "image-agent/image_entry"),
    "youtube": ("youtube-agent", "youtube-agent/youtube_entry"),
    "message": ("message", "message-agent/message_entry"),
    "prompt": ("prompt", "prompt-agent/prompt_entry"),
}


def get_fastmarket_command_help(cmd_name: str) -> CommandInfo | None:
    """Extract help text from a fast-market command by running it with --help."""
    entry = _COMMAND_ENTRY_POINTS.get(cmd_name)
    if not entry:
        return None

    console_script, module_path = entry
    project_root = Path(__file__).parents[3]

    entry_points_to_try = [
        ([console_script, "--help"], None),
        ([sys.executable, "-m", module_path, "--help"], None),
    ]

    agent_dir = project_root / module_path.split("/")[0]
    if agent_dir.exists():
        entry_points_to_try.append(
            ([sys.executable, "-m", module_path, "--help"], str(agent_dir))
        )

    if cmd_name == "prompt":
        prompt_dir = project_root / "prompt-agent"
        if prompt_dir.exists():
            entry_points_to_try.append(
                (
                    [
                        sys.executable,
                        "-c",
                        f"import sys; sys.path.insert(0, '{prompt_dir}'); "
                        f"from prompt_entry import main; "
                        f"import sys; sys.argv = ['prompt', '--help']; main()",
                    ],
                    str(prompt_dir),
                )
            )

    for entry_point, cwd in entry_points_to_try:
        try:
            result = subprocess.run(
                entry_point,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=cwd,
            )

            if result.returncode == 0 and result.stdout:
                return _parse_click_help(cmd_name, result.stdout)

        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.debug(
                "command_help_extraction_failed",
                command=cmd_name,
                entry=entry_point,
                error=str(exc),
            )
            continue

    return None

    console_script, module_path = entry
    project_root = Path(__file__).parents[3]

    entry_points_to_try = [
        [console_script, "--help"],
        [sys.executable, "-m", module_path, "--help"],
    ]

    agent_dir = project_root / module_path.split("/")[0]
    if agent_dir.exists():
        entry_points_to_try.append([sys.executable, "-m", module_path, "--help"])

    for entry_point in entry_points_to_try:
        try:
            result = subprocess.run(
                entry_point,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0 and result.stdout:
                return _parse_click_help(cmd_name, result.stdout)

        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.debug(
                "command_help_extraction_failed",
                command=cmd_name,
                entry=entry_point,
                error=str(exc),
            )
            continue

    return None


def _parse_click_help(cmd_name: str, help_text: str) -> CommandInfo:
    """Parse Click-style help text into structured info."""
    lines = help_text.split("\n")

    description = ""
    in_usage = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if (
            "Commands:" in stripped
            or "Available Commands:" in stripped
            or "Arguments:" in stripped
        ):
            break
        if "Usage:" in stripped:
            in_usage = True
            continue
        if (
            stripped
            and not stripped.startswith("-")
            and not stripped.startswith("Options:")
            and not in_usage
        ):
            if not description:
                description = stripped
                break

    usage = f"{cmd_name} [OPTIONS]"
    for line in lines:
        if "Usage:" in line:
            usage_line = line.split("Usage:")[-1].strip()
            if usage_line:
                usage = usage_line
            break

    examples = []
    in_commands = False
    for line in lines:
        if "Commands:" in line or "Available Commands:" in line:
            in_commands = True
            continue
        if in_commands and line.strip():
            stripped = line.strip()
            if (
                stripped.startswith("Usage:")
                or stripped.startswith("Options:")
                or stripped.startswith("Arguments:")
            ):
                break
            if not stripped.startswith("-"):
                parts = stripped.split(None, 1)
                if parts:
                    cmd_part = parts[0]
                    if cmd_part and cmd_part not in ("--help", "--version"):
                        examples.append(f"{cmd_name} {cmd_part}")
        if len(examples) >= 3:
            break

    if len(examples) < 3:
        examples = _extract_examples_from_text(help_text, cmd_name)

    if not description:
        description = f"{cmd_name} command-line tool"

    return CommandInfo(
        name=cmd_name,
        description=description,
        usage=usage,
        examples=examples[:3],
    )


def _extract_examples_from_text(help_text: str, cmd_name: str) -> list[str]:
    """Extract example commands from help text."""
    examples = []
    lines = help_text.split("\n")

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{cmd_name} ") and not stripped.startswith(
            f"{cmd_name}.py"
        ):
            example = stripped.split("#")[0].strip()
            if example and len(example) < 80:
                examples.append(example)

    return examples[:3]
