from __future__ import annotations

import click


def create_cli_group(
    tool_name: str,
    description: str | None = None,
    default_command: str | None = None,
    default_args: dict | None = None,
) -> click.Group:
    """Standard Click group setup for fast-market tools.

    Args:
        tool_name: Name of the tool/agent
        description: Short description shown in --help (defaults to tool_name if None)
        default_command: Name of a registered subcommand to invoke when no subcommand is given
        default_args: Keyword arguments to pass to the default command (e.g. flag values)
    """

    @click.group(invoke_without_command=True, help=description)
    @click.option(
        "--verbose", "-v", is_flag=True, default=False, help="Show logs on stderr."
    )
    @click.pass_context
    def main(ctx: click.Context, verbose: bool) -> None:
        ctx.ensure_object(dict)
        ctx.obj["verbose"] = verbose
        ctx.obj["tool_name"] = tool_name

        if default_command and ctx.invoked_subcommand is None:
            cmd = ctx.command.get_command(ctx, default_command)
            if cmd:
                ctx.invoke(cmd, **(default_args or {}))

    return main
