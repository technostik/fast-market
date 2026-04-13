from __future__ import annotations

from commands.setup.register import register as setup_register
from commands.autocomplete.register import register as autocomplete_register
from commands.config.register import register as config_register
from commands.backup.register import register as backup_register
from commands.data.register import register as data_register

main = setup_register()
autocomplete_cmd = autocomplete_register()
main.add_command(autocomplete_cmd, name="autocomplete-configure")
config_cmd = config_register()
main.add_command(config_cmd, name="config")
backup_cmd = backup_register()
main.add_command(backup_cmd, name="backup")
data_cmd = data_register()
main.add_command(data_cmd, name="data")
