import click
from commands.base import CommandManifest
from commands.helpers import context,emit,human_results,results_payload
from core.services import latest,dedupe
def register(plugin_manifests):
 @click.command('dashboard')
 @click.option('--json','json_output',is_flag=True)
 def command(json_output):
  providers,variables,topics,_,db=context(); results=latest(variables,providers,db); news=[]
  try:
   for topic in topics: news.extend(providers['google_news'].fetch(topic))
  except Exception as exc: news_error=str(exc)
  else: news_error=None
  news=dedupe(news)[:20]; payload=results_payload(results); payload['news']=[{'topic':i.topic,'title':i.title,'source':i.source,'published_at':i.published_at,'url':i.url} for i in news];payload['news_error']=news_error
  human=human_results(results)+'\n\nNEWS\n'+'\n'.join(f'{i.published_at} · {i.source} · {i.title}\n{i.url}' for i in news)
  emit(payload if json_output else human,json_output)
  if any(r.error for r in results) or news_error: raise click.exceptions.Exit(1)
 return CommandManifest('dashboard',command)
