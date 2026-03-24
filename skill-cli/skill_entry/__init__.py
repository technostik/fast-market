from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_COMMON_PARENT = _ROOT.parent
for p in [str(_ROOT), str(_COMMON_PARENT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from common.cli.base import create_cli_group
from common.core.config import requires_common_config

requires_common_config("skill", [])

main = create_cli_group("skill")


def _load():
    from commands.skill.register import register as skill_register

    manifest = skill_register({})
    skill_group = manifest.click_command
    for cmd_name, cmd in skill_group.commands.items():
        main.add_command(cmd, name=cmd_name)


_load()

__all__ = ["main"]
