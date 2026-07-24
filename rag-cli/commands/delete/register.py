from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import get_rag_store, out
from commands.param_types import COLLECTION_NAME, DOCUMENT_HANDLE


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("delete", help="Delete a document from a collection or purge entirely.")
    @click.argument("handle", type=DOCUMENT_HANDLE)
    @click.option("--collection", "-c", default=None, type=COLLECTION_NAME, help="Remove from this collection only.")
    @click.option("--purge", is_flag=True, default=False, help="Delete document and tree everywhere.")
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    def delete_cmd(handle, collection, purge, fmt):
        store, _ = get_rag_store()
        doc = store.get_document_by_handle(handle)
        if not doc:
            raise click.ClickException(f"Document {handle!r} not found")

        if purge:
            store.purge_document(doc.id)
            out({"deleted": True, "handle": handle, "scope": "purge"}, fmt)
            return

        if not collection:
            raise click.ClickException(
                "Specify --collection <name> to remove from a collection, or --purge to delete everywhere."
            )

        from core.collection_pointer import resolve_collection_name
        coll_name = resolve_collection_name(collection)
        coll = store.get_collection(coll_name)
        if not coll:
            raise click.ClickException(f"Collection {coll_name!r} not found")

        removed = store.remove_collection_member(coll.id, doc.id)
        if removed:
            out({"deleted": True, "handle": handle, "collection": coll_name}, fmt)
        else:
            raise click.ClickException(
                f"Document {handle!r} is not in collection {coll_name!r}"
            )

    return CommandManifest(name="delete", click_command=delete_cmd)
