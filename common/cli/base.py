from __future__ import annotations

import click


def create_cli_group(tool_name: str) -> click.Group:
    """Standard Click group setup for fast-market tools."""

    @click.group()
    @click.option("--verbose", "-v", is_flag=True, default=False, help="Show logs on stderr.")
    @click.pass_context
    def main(ctx: click.Context, verbose: bool) -> None:
        ctx.ensure_object(dict)
        ctx.obj["verbose"] = verbose
        ctx.obj["tool_name"] = tool_name

    return main
