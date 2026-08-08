from __future__ import annotations

import json

import click

from commands.base import CommandManifest
from commands.helpers import build_engine, out


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys())

    @click.group(
        "field",
        help="Declare and manage soft fields stored in document metadata.",
    )
    def field_group():
        pass

    @field_group.command("list", help="Show declared fields.")
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def field_list(ctx, fmt, **kwargs):
        verbose = ctx.obj.get("verbose", True)
        _engine, _plugins, store = build_engine(verbose)
        out(store.list_field_definitions(), fmt)

    @field_group.command("create", help="Declare a new soft field.")
    @click.option(
        "--name", required=True, help="Field name (lowercase, [a-z0-9_])."
    )
    @click.option(
        "--applies-to",
        "applies_to",
        type=click.Choice(["all"] + source_choices),
        default="all",
        help="Source plugin the field applies to.",
    )
    @click.option("--description", default=None, help="Optional description.")
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def field_create(ctx, name, applies_to, description, fmt, **kwargs):
        verbose = ctx.obj.get("verbose", True)
        _engine, _plugins, store = build_engine(verbose)
        try:
            created = store.create_field_definition(
                name, applies_to=applies_to, description=description
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        out(created, fmt)

    @field_group.command("delete", help="Remove a field declaration (values kept).")
    @click.option("--name", required=True, help="Field name.")
    @click.pass_context
    def field_delete(ctx, name, **kwargs):
        verbose = ctx.obj.get("verbose", True)
        _engine, _plugins, store = build_engine(verbose)
        if store.delete_field_definition(name):
            click.echo(f"Deleted field '{name}'.")
        else:
            click.echo(f"No such field '{name}'.", err=True)
            ctx.exit(1)

    @field_group.command("missing", help="List documents missing a field value.")
    @click.option("--name", required=True, help="Field name.")
    @click.option(
        "--source",
        type=click.Choice(source_choices),
        default=None,
        help="Restrict to one source plugin.",
    )
    @click.option(
        "--limit", "-l", type=int, default=1000, help="Max documents to list."
    )
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def field_missing(ctx, name, source, limit, fmt, **kwargs):
        verbose = ctx.obj.get("verbose", True)
        _engine, _plugins, store = build_engine(verbose)
        try:
            docs = store.get_documents_missing_field(
                name, source=source, limit=limit
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        out(docs, fmt)

    @field_group.command("set", help="Set a field value on a document.")
    @click.option("--name", required=True, help="Field name.")
    @click.option(
        "--source", required=True, type=click.Choice(source_choices), help="Source plugin."
    )
    @click.option(
        "--id", "source_id", required=True, help="Source item id (e.g. video id)."
    )
    @click.option(
        "--value", required=True, help="Value as JSON (e.g. '{\"label\":\"x\"}')."
    )
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def field_set(ctx, name, source, source_id, value, fmt, **kwargs):
        verbose = ctx.obj.get("verbose", True)
        _engine, _plugins, store = build_engine(verbose)
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise click.ClickException(f"Invalid --value JSON: {exc}") from exc
        try:
            updated = store.set_document_field(source, source_id, name, parsed)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        if not updated:
            click.echo(f"No document for {source}/{source_id}.", err=True)
            ctx.exit(1)
        doc = store.get_document(source, source_id)
        out(doc, fmt)

    return CommandManifest(name="field", click_command=field_group)
