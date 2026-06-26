from __future__ import annotations

import os
import sys

import click
from click.shell_completion import get_completion_class


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

    def _set_profile(ctx: click.Context, param: click.Parameter, value: str | None):
        """Eagerly export the chosen profile so all path/config lookups see it."""
        if value:
            from common.core.profile import validate_profile_name, ProfileError

            try:
                validate_profile_name(value)
            except ProfileError as exc:
                raise click.BadParameter(str(exc))
            os.environ["FASTMARKET_PROFILE"] = value
        return value

    @click.group(invoke_without_command=True, help=description)
    @click.option(
        "--profile",
        "-P",
        default=None,
        is_eager=True,
        expose_value=True,
        callback=_set_profile,
        metavar="NAME",
        help="Persona/profile to use (overrides FASTMARKET_PROFILE and the active-profile file).",
    )
    @click.option(
        "--verbose", "-v", is_flag=True, default=False, help="Show logs on stderr."
    )
    @click.option(
        "--install-completion",
        is_flag=True,
        default=False,
        help="Print shell completion script and install instructions",
    )
    @click.option(
        "--show-completion",
        is_flag=True,
        default=False,
        help="Print shell completion script",
    )
    @click.pass_context
    def main(ctx: click.Context, profile: str | None, verbose: bool, install_completion: bool, show_completion: bool) -> None:
        ctx.ensure_object(dict)
        ctx.obj["verbose"] = verbose
        ctx.obj["tool_name"] = tool_name
        ctx.obj["profile"] = profile

        if install_completion or show_completion:
            _handle_completion(ctx, tool_name, install_completion, show_completion)
            ctx.exit()

        if default_command and ctx.invoked_subcommand is None:
            cmd = ctx.command.get_command(ctx, default_command)
            if cmd:
                ctx.invoke(cmd, **(default_args or {}))

    return main


def _detect_shell() -> str:
    """Detect current or preferred shell."""
    shell = os.environ.get("SHELL", "")
    if "fish" in shell:
        return "fish"
    if "zsh" in shell:
        return "zsh"
    return "bash"


def _handle_completion(
    ctx: click.Context,
    tool_name: str,
    install_completion: bool,
    show_completion: bool,
) -> None:
    shell = _detect_shell()
    prog_name = ctx.find_root().info_name or tool_name
    complete_var = f"_{prog_name.upper().replace('-', '_')}_COMPLETE"

    comp_class = get_completion_class(shell)
    if comp_class is None:
        click.echo(
            f"Error: Unsupported shell '{shell}' (expected bash, zsh, or fish).",
            err=True,
        )
        return

    completer = comp_class(
        cli=ctx.command,
        ctx_args={},
        prog_name=prog_name,
        complete_var=complete_var,
    )

    source_code = completer.source()

    if show_completion:
        click.echo(source_code)
        return

    # --install-completion
    rc_map = {
        "bash": "~/.bashrc",
        "zsh": "~/.zshrc",
        "fish": "~/.config/fish/config.fish",
    }
    rc_file = rc_map.get(shell, "~/.bashrc")

    click.echo(f"# Add the following to {rc_file}:", err=True)
    click.echo("", err=True)
    if shell == "fish":
        click.echo(f"  {prog_name} --show-completion | source")
    else:
        click.echo(f"  eval \"$({prog_name} --show-completion)\"")
    click.echo("", err=True)
    click.echo("# Or run this one-liner:", err=True)
    if shell == "fish":
        click.echo(f"  {prog_name} --show-completion | source")
    else:
        click.echo(f"  echo 'eval \"$({prog_name} --show-completion)\"' >> {rc_file}")
