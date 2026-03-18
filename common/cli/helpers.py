from __future__ import annotations

import json

import click


def out(data: object, fmt: str) -> None:
    """Standard output formatting for fast-market tools."""
    if fmt == "json":
        click.echo(json.dumps(data, ensure_ascii=False, default=str))
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
