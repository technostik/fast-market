from __future__ import annotations

import click
from commands.setup.register import register as setup_register
from commands.autocomplete.register import register as autocomplete_register

main = setup_register()
autocomplete_cmd = autocomplete_register()
main.add_command(autocomplete_cmd, name="autocomplete-configure")
