import click
from commands.base import CommandManifest
from commands.helpers import context,emit
from core.config import config_path,default_text,load_config
from common.cli.helpers import open_editor
def register(plugin_manifests):
 @click.command('setup')
 @click.option('--json','json_output',is_flag=True)
 def command(json_output):
  path=config_path()
  if not path.exists(): path.parent.mkdir(parents=True,exist_ok=True);path.write_text(default_text())
  open_editor(path)
  providers,_,_,_=context()
  emit({'config':str(path),'valid':True} if json_output else f'Validated {path}',json_output)
 return CommandManifest('setup',command)
