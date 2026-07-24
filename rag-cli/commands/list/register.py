from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import get_rag_store, out
from commands.param_types import COLLECTION_NAME


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("list", help="List indexed documents.")
    @click.option("--collection", "-c", default=None, type=COLLECTION_NAME, help="Filter by collection.")
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    def list_cmd(collection, fmt):
        store, _ = get_rag_store()
        if collection:
            coll = store.get_collection(collection)
            if not coll:
                raise click.ClickException(f"Collection {collection!r} not found")
            docs = store.list_documents_in_collection(coll.id)
        else:
            docs = store.list_documents_in_collection()
        out(docs, fmt)

    return CommandManifest(name="list", click_command=list_cmd)
