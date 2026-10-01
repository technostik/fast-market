import click
from datetime import datetime,timezone,timedelta
from commands.base import CommandManifest
from commands.helpers import context,emit
from core.services import dedupe
def register(plugin_manifests):
 @click.command('news')
 @click.option('--topic')
 @click.option('--variable')
 @click.option('--since',default='24h')
 @click.option('--limit','limit',type=int,default=20)
 @click.option('--json','json_output',is_flag=True)
 def command(topic,variable,since,limit,json_output):
  providers,variables,topics,_,_=context()
  if topic and variable: raise click.ClickException("--topic and --variable are mutually exclusive")
  if variable:
   var=next((x for x in variables if x.id==variable),None)
   if not var: raise click.ClickException(f"Unknown variable '{variable}'")
   selected=[t for t in topics if t.id in var.news_topics]
  else: selected=[t for t in topics if not topic or t.id==topic]
  if topic and not selected: raise click.ClickException(f"Unknown topic '{topic}'")
  items=[]
  for t in selected: items.extend(providers['google_news'].fetch(t))
  items=dedupe(items)[:limit]; payload={'generated_at':datetime.now(timezone.utc).isoformat(),'news':[{'topic':i.topic,'title':i.title,'source':i.source,'published_at':i.published_at,'url':i.url} for i in items]}
  emit(payload if json_output else '\n'.join(f'{i.published_at} · {i.source} · {i.title}\n{i.url}' for i in items),json_output)
 return CommandManifest('news',command)
