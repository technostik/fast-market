from __future__ import annotations

import sys

import click
from fastapi import APIRouter, HTTPException

from commands.base import CommandManifest
from commands.helpers import build_engine, out


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("get")
    @click.argument("handle")
    @click.option(
        "--what", type=click.Choice(["meta", "content", "all"]), default="meta"
    )
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def get_cmd(ctx, handle, what, fmt, **kwargs):
        _, _, store = build_engine(ctx.obj["verbose"])
        doc = store.get_document_by_handle(handle)
        if not doc:
            click.echo(f"not found: {handle}", err=True)
            sys.exit(1)
        if what == "content":
            click.echo(doc["raw_text"])
            return
        if what == "meta":
            out({k: v for k, v in doc.items() if k != "raw_text"}, fmt)
            return
        if fmt == "json":
            out(doc, fmt)
        else:
            for key, value in doc.items():
                if key == "raw_text":
                    click.echo(f"\n--- content ({len(value)} chars) ---\n")
                    click.echo(value)
                else:
                    click.echo(f"  {key}: {value}")

    return CommandManifest(
        name="get",
        click_command=get_cmd,
        api_router=_build_router(),
    )


def _build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/document/{source_plugin}/{source_id:path}")
    def get_document(source_plugin: str, source_id: str):
        from common.core.config import load_config
        from storage.sqlite_store import SQLiteStore

        config = load_config()
        store = SQLiteStore(config.get("db_path"))
        doc = store.get_document(source_plugin, source_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return doc

    @router.get("/handle/{handle}")
    def get_by_handle(handle: str):
        from common.core.config import load_config
        from storage.sqlite_store import SQLiteStore

        config = load_config()
        store = SQLiteStore(config.get("db_path"))
        doc = store.get_document_by_handle(handle)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return doc

    return router
