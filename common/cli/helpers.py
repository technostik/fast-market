from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import click
import yaml

from common.core.yaml_utils import dump_yaml


def out(data: object, fmt: str) -> None:
    """Standard output formatting for fast-market tools."""
    if fmt == "json":
        click.echo(json.dumps(data, ensure_ascii=False, default=str))
    elif fmt == "yaml":
        click.echo(dump_yaml(data, sort_keys=False))
    else:
        _print_text(data)


def _print_text(data: object) -> None:
    """Print data in human-readable text format."""
    if isinstance(data, list):
        for item in data:
            _print_text(item)
            click.echo("")
    elif isinstance(data, dict):
        for key, value in data.items():
            if key == "raw_text":
                continue
            click.echo(f"  {key}: {value}")
    else:
        click.echo(str(data))


def get_editor() -> str:
    """Get the default editor from environment variables."""
    editor = (
        subprocess.run(
            ["git", "var", "GIT_EDITOR"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        or os.environ.get("EDITOR")
        or "nano"
    )
    return editor


def open_editor(file_path: Path) -> None:
    """Open a file in the default editor."""
    editor = get_editor()
    subprocess.run([editor, str(file_path)], check=True)
