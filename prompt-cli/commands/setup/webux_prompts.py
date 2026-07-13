from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click
import yaml

from common.cli.helpers import out


def _default_seed_path() -> Path:
    import common

    repo_root = Path(common.__file__).resolve().parents[1]
    candidate = (
        repo_root / "webux-cli" / "webux" / "resources" / "webux_prompts.yaml"
    )
    return candidate


def _load_seed(path: Path) -> list[dict]:
    if not path.exists():
        click.echo(f"Error: seed file not found: {path}", err=True)
        sys.exit(1)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    prompts = data.get("prompts")
    if not isinstance(prompts, list):
        click.echo(f"Error: seed file has no 'prompts' list: {path}", err=True)
        sys.exit(1)
    return prompts


def register(plugin_manifests: dict = None) -> click.Group:
    @click.group("webux")
    def webux():
        """Manage webux component prompts (seed/import)."""
        pass

    @webux.command("import")
    @click.option(
        "--file",
        "-f",
        type=click.Path(exists=True),
        default=None,
        help="Seed YAML file (default: webux-cli/webux/resources/webux_prompts.yaml)",
    )
    @click.option(
        "--force",
        is_flag=True,
        default=False,
        help="Overwrite prompts that already exist",
    )
    def import_cmd(file, force):
        """Import webux prompts from the seed file into the prompt store.

        Without --force, existing prompts are skipped (only missing ones are
        created). With --force, every seed prompt overwrites its store entry,
        so the store always mirrors the seed. `webux serve` calls this with
        --force on every startup.
        """
        from core.models import Prompt
        from storage.store import PromptStore

        seed_path = Path(file) if file else _default_seed_path()
        prompts = _load_seed(seed_path)
        store = PromptStore()

        created = 0
        updated = 0
        skipped = 0
        for entry in prompts:
            name = entry.get("name")
            if not name:
                click.echo("Error: seed entry missing 'name'", err=True)
                sys.exit(1)
            content = entry.get("content", "")
            existing = store.get_prompt(name)
            if existing and not force:
                skipped += 1
                continue
            prompt = Prompt(
                name=name,
                content=content,
                description=entry.get("description", ""),
                model_provider=entry.get("model_provider", "") or "",
                model_name=entry.get("model_name", "") or "",
                temperature=float(entry.get("temperature", 0.7)),
                max_tokens=int(entry.get("max_tokens", 2048)),
                created_at=existing.created_at if (existing and force) else datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            if existing and force:
                store.update_prompt(
                    name,
                    content=content,
                    description=prompt.description,
                    model_provider=prompt.model_provider,
                    model_name=prompt.model_name,
                    temperature=prompt.temperature,
                    max_tokens=prompt.max_tokens,
                )
                updated += 1
            else:
                store.create_prompt(prompt)
                created += 1

        click.echo(
            f"✓ webux prompts import: {created} created, {updated} updated, {skipped} skipped"
        )

    @webux.command("list")
    def list_cmd():
        """List webux seed prompts and whether they exist in the store."""
        from storage.store import PromptStore

        seed_path = _default_seed_path()
        prompts = _load_seed(seed_path)
        store = PromptStore()
        rows = []
        for entry in prompts:
            name = entry.get("name", "")
            rows.append(
                {
                    "name": name,
                    "exists": bool(store.get_prompt(name)),
                    "description": entry.get("description", ""),
                }
            )
        out(rows, "text")
        missing = [r["name"] for r in rows if not r["exists"]]
        if missing:
            click.echo(
                f"\n{len(missing)} prompt(s) missing — run: prompt setup webux import",
                err=True,
            )
            sys.exit(1)

    return webux
