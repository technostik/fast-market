import click
from commands.base import CommandManifest
from commands.helpers import context,emit,human_results,results_payload
from core.services import latest,dedupe
def register(plugin_manifests):
 @click.command('dashboard')
 @click.option('--json','json_output',is_flag=True)
 @click.option('--last',type=click.IntRange(0),default=3,show_default=True,help='Show only the last N news items.')
 @click.option('--nolinks',is_flag=True,default=False,help='Omit URLs from news output.')
 def command(json_output,last,nolinks):
  providers,variables,topics,_,db=context(); results=latest(variables,providers,db); news=[]
  try:
   for topic in topics: news.extend(providers['google_news'].fetch(topic))
  except Exception as exc: news_error=str(exc)
  else: news_error=None
  news=dedupe(news)[:last]; payload=results_payload(results); payload['news']=[{'topic':i.topic,'title':i.title,'source':i.source,'published_at':i.published_at} | ({'url':i.url} if not nolinks else {}) for i in news];payload['news_error']=news_error
  human=human_results(results)
  if news: human+='\n\nNEWS\n'+'\n'.join(f'{i.published_at} · {i.source} · {i.title}' + ('' if nolinks else f'\n{i.url}') for i in news)
  emit(payload if json_output else human,json_output)
  if any(r.error for r in results) or news_error: raise click.exceptions.Exit(1)
 return CommandManifest('dashboard',command)
