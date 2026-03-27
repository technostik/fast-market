from __future__ import annotations

import click
from auto_click_auto import enable_click_shell_completion


def create_cli_group(tool_name: str, default_command: str | None = None) -> click.Group:
    """Standard Click group setup for fast-market tools.

    Args:
        tool_name: Name of the tool/agent
        default_command: Name of a registered subcommand to invoke when no subcommand is given
    """

    @click.group(invoke_without_command=True)
    @click.option(
        "--verbose", "-v", is_flag=True, default=True, help="Show logs on stderr."
    )
    @click.pass_context
    def main(ctx: click.Context, verbose: bool) -> None:
        ctx.ensure_object(dict)
        ctx.obj["verbose"] = verbose
        ctx.obj["tool_name"] = tool_name
        enable_click_shell_completion(program_name=tool_name)

        if default_command and ctx.invoked_subcommand is None:
            cmd = ctx.command.get_command(ctx, default_command)
            if cmd:
                ctx.invoke(cmd)

    return main
