import click
from commands.base import CommandManifest
from commands.helpers import context,emit,results_payload,human_results
from core.services import latest
def register(plugin_manifests):
 @click.command('get')
 @click.argument('variables',nargs=-1)
 @click.option('--json','json_output',is_flag=True)
 def command(variables,json_output):
  providers,configured,_,_,db=context(); selected=[v for v in configured if not variables or v.id in variables]
  unknown=set(variables)-{v.id for v in configured}
  if unknown: raise click.ClickException('Unknown variable(s): '+', '.join(sorted(unknown)))
  result=latest(selected,providers,db); emit(results_payload(result) if json_output else human_results(result),json_output)
  if any(x.error for x in result): raise click.exceptions.Exit(1)
 return CommandManifest('get',command)
