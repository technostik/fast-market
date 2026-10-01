from pathlib import Path
import click,yaml
from commands.base import CommandManifest
from commands.helpers import context,emit
from core.config import config_path,default_text,load_config
from core.services import latest
def register(plugin_manifests):
 @click.command('wizard')
 @click.option('--json','json_output',is_flag=True)
 def command(json_output):
  path=config_path()
  if not path.exists(): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(default_text())
  providers,variables,topics,feeds,db=context()
  action=click.prompt('Action',type=click.Choice(['list','add-catalog','remove-variable','add-topic','remove-topic','quit']),default='list')
  raw=yaml.safe_load(path.read_text())
  if action=='add-catalog':
   catalog=yaml.safe_load((Path(__file__).resolve().parents[2]/'catalog.yaml').read_text()); choices=[v['id'] for v in catalog['variables'] if v['id'] not in {x['id'] for x in raw['variables']}]; chosen=click.prompt('Catalog variable',type=click.Choice(choices)); item=next(v for v in catalog['variables'] if v['id']==chosen)
   # Test before persisting, as required.
   candidate=next(v for v in variables if v.id==chosen) if False else None
   provider=providers[item['provider']]
   try: provider.fetch_latest(item['symbol'])
   except Exception as exc:
    click.echo(f'Test fetch failed: {exc}',err=True)
    if not click.confirm('Save it anyway?',default=False): return
   raw['variables'].append(item)
  elif action=='remove-variable':
   ident=click.prompt('Variable id',type=click.Choice([v['id'] for v in raw['variables']]));raw['variables']=[v for v in raw['variables'] if v['id']!=ident]
  elif action=='add-topic':
   ident=click.prompt('Topic id'); raw['news_topics'].append({'id':ident,'label':click.prompt('Label'),'query':click.prompt('Query'),'lang':click.prompt('Language',default='en',type=click.Choice(['en','fr']))})
  elif action=='remove-topic':
   ident=click.prompt('Topic id',type=click.Choice([t['id'] for t in raw['news_topics']])); raw['news_topics']=[t for t in raw['news_topics'] if t['id']!=ident]
  elif action=='list':
   emit({'variables':raw['variables'],'news_topics':raw['news_topics']} if json_output else yaml.safe_dump(raw,sort_keys=False),json_output);return
  else:return
  path.write_text(yaml.safe_dump(raw,sort_keys=False)); load_config(providers); emit({'config':str(path),'saved':True} if json_output else 'Saved and validated configuration.',json_output)
 return CommandManifest('wizard',command)
