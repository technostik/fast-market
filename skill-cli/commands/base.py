from dataclasses import dataclass

import click


@dataclass
class CommandManifest:
    name: str
    click_command: click.Command
