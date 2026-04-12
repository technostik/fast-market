from __future__ import annotations

from commands.setup.register import register as setup_register
from commands.autocomplete.register import register as autocomplete_register
from commands.config.register import register as config_register
from commands.workdir.register import register as workdir_register

main = setup_register()
autocomplete_cmd = autocomplete_register()
main.add_command(autocomplete_cmd, name="autocomplete-configure")
config_cmd = config_register()
main.add_command(config_cmd, name="config")
workdir_cmd = workdir_register()
main.add_command(workdir_cmd, name="workdir")
