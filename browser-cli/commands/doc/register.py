from __future__ import annotations

import click
from commands.base import CommandManifest
from commands.helpers import out


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("doc")
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Output format.",
    )
    def doc_cmd(fmt: str) -> None:
        """Display the agent-browser command reference documentation."""
        from pathlib import Path

        doc_path = Path(__file__).resolve().parents[2] / "browser-agent.md"
        if not doc_path.exists():
            raise click.ClickException(f"Documentation not found: {doc_path}")

        content = doc_path.read_text()

        if fmt == "json":
            out({"documentation": content, "source": str(doc_path)}, fmt)
        else:
            click.echo_via_pager(content)

    return CommandManifest(
        name="doc",
        click_command=doc_cmd,
    )
