import click
from commands.base import CommandManifest
from commands.helpers import context,emit,results_payload,human_results
from core.services import latest
def register(plugin_manifests):
 @click.command('get')
 @click.argument('variables',nargs=-1)
 @click.option('--json','json_output',is_flag=True)
 @click.option('--refresh',is_flag=True,default=False,help='Force live refresh, bypassing values fetched less than 1h ago.')
 @click.option('--main-currency',type=click.Choice(['USD','EUR']),default='USD',show_default=True,help='Main display currency; the other is shown as secondary.')
 def command(variables,json_output,refresh,main_currency):
  providers,configured,_,_,db=context(); selected=[v for v in configured if not variables or v.id in variables]
  unknown=set(variables)-{v.id for v in configured}
  if unknown: raise click.ClickException('Unknown variable(s): '+', '.join(sorted(unknown)))
  result=latest(selected,providers,db,force=refresh,main_currency=main_currency); emit(results_payload(result) if json_output else human_results(result),json_output)
  if any(x.error for x in result): raise click.exceptions.Exit(1)
 return CommandManifest('get',command)
