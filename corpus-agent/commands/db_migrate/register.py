from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import out


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("db-migrate")
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def db_migrate_cmd(ctx, fmt):
        from common.core.config import load_config
        from storage.sqlite_store import SQLiteStore

        config = load_config()
        store = SQLiteStore(config.get("db_path"))
        out(
            {
                "status": "ok",
                "db_path": config.get("db_path"),
                "message": "alembic upgrade head complete",
            },
            fmt,
        )
        del store

    return CommandManifest(name="db-migrate", click_command=db_migrate_cmd)
