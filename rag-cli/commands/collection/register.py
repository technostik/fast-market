from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import get_rag_store, out
from commands.param_types import COLLECTION_NAME
from core.collection_pointer import write_active_collection, read_active_collection


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("collection")
    def collection_group():
        """Manage RAG collections."""
        pass

    @collection_group.command("create")
    @click.argument("name")
    @click.option("--description", "-d", default="", help="Collection description.")
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    def create_cmd(name, description, fmt):
        store, _ = get_rag_store()
        try:
            result = store.create_collection(name, description)
            out(result, fmt)
        except ValueError as exc:
            raise click.ClickException(str(exc))

    @collection_group.command("use")
    @click.argument("name", type=COLLECTION_NAME)
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    def use_cmd(name, fmt):
        store, _ = get_rag_store()
        coll = store.get_collection(name)
        if not coll:
            raise click.ClickException(f"Collection {name!r} not found")
        write_active_collection(name)
        out({"active_collection": name}, fmt)

    @collection_group.command("list")
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    def list_cmd(fmt):
        store, _ = get_rag_store()
        collections = store.list_collections()
        active = read_active_collection()
        results = []
        for c in collections:
            entry = {**c, "active": c["name"] == active}
            results.append(entry)
        out(results, fmt)

    @collection_group.command("show")
    @click.argument("name", type=COLLECTION_NAME)
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    def show_cmd(name, fmt):
        store, _ = get_rag_store()
        coll = store.get_collection(name)
        if not coll:
            raise click.ClickException(f"Collection {name!r} not found")
        members = store.get_collection_members(coll.id)
        result = {
            "name": coll.name,
            "description": coll.description,
            "members": members,
        }
        out(result, fmt)

    @collection_group.command("delete")
    @click.argument("name", type=COLLECTION_NAME)
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    def delete_cmd(name, fmt):
        store, _ = get_rag_store()
        deleted = store.delete_collection(name)
        if deleted:
            out({"deleted": True, "name": name}, fmt)
        else:
            raise click.ClickException(f"Collection {name!r} not found")

    return CommandManifest(name="collection", click_command=collection_group)
