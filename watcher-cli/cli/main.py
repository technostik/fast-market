from __future__ import annotations
import logging
from pathlib import Path
from common.cli.base import create_cli_group
from common.core.config import load_tool_config,requires_common_config
from common.core.registry import discover_commands,discover_plugins
requires_common_config('watcher',[])
main=create_cli_group('watcher',description='Personal market and macro watchlist.')
ROOT=Path(__file__).resolve().parents[1]
def _load():
 logging.basicConfig(level=logging.CRITICAL,force=True); config=load_tool_config('watcher'); plugins=discover_plugins(config,tool_root=ROOT); commands=discover_commands(plugins,tool_root=ROOT)
 for manifest in commands.values(): main.add_command(manifest.click_command)
_load()
