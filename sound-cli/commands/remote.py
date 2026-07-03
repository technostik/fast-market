from __future__ import annotations

from pathlib import Path

import click


def run_remote_charisma(input_path: Path) -> dict:
    try:
        from modal_client.app import app
        from modal_client.remote_steps import remote_charisma
    except ImportError as exc:
        raise click.ClickException(f"modal not installed: {exc}") from exc
    click.echo("Running charisma on Modal...", err=True)
    with app.run():
        result = remote_charisma.remote(input_path.read_bytes(), input_path.name)
    return result


def run_remote_normalize_volume_measure(input_path: Path) -> dict:
    try:
        from modal_client.app import app
        from modal_client.remote_steps import remote_normalize_volume_measure
    except ImportError as exc:
        raise click.ClickException(f"modal not installed: {exc}") from exc
    click.echo("Running normalize-volume measure on Modal...", err=True)
    with app.run():
        result = remote_normalize_volume_measure.remote(input_path.read_bytes(), input_path.name)
    return result


def run_remote_normalize_volume_apply(input_path: Path, output_path: Path, target_db: float) -> dict:
    try:
        from modal_client.app import app
        from modal_client.remote_steps import remote_normalize_volume_apply
    except ImportError as exc:
        raise click.ClickException(f"modal not installed: {exc}") from exc
    click.echo("Running normalize-volume apply on Modal...", err=True)
    with app.run():
        result = remote_normalize_volume_apply.remote(input_path.read_bytes(), input_path.name, target_db)
    output_path.write_bytes(result["output_bytes"])
    return result
