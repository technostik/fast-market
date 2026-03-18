from __future__ import annotations

import sys

import click
from fastapi import APIRouter, HTTPException

from commands.base import CommandManifest
from commands.helpers import build_engine, out


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("delete")
    @click.argument("handle")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def delete_cmd(ctx, handle, fmt, **kwargs):
        _, _, store = build_engine(ctx.obj["verbose"])
        deleted = store.delete_document_by_handle(handle)
        if deleted:
            out({"deleted": True, "handle": handle}, fmt)
        else:
            click.echo(f"not found: {handle}", err=True)
            sys.exit(1)

    return CommandManifest(
        name="delete",
        click_command=delete_cmd,
        api_router=_build_router(),
    )


def _build_router() -> APIRouter:
    router = APIRouter()

    @router.delete("/document/{source_plugin}/{source_id:path}")
    def delete_document(source_plugin: str, source_id: str):
        from common.core.config import load_config
        from storage.sqlite_store import SQLiteStore

        config = load_config()
        store = SQLiteStore(config.get("db_path"))
        deleted = store.delete_document(source_plugin, source_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"deleted": True, "source_plugin": source_plugin, "source_id": source_id}

    return router
