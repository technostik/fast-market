import click
from datetime import date
from commands.base import CommandManifest
from commands.helpers import context,emit,parse_since
from core.services import history
def register(plugin_manifests):
 @click.command('history')
 @click.argument('variable')
 @click.option('--since',default='1y')
 @click.option('--to','end',default=None)
 @click.option('--json','json_output',is_flag=True)
 def command(variable,since,end,json_output):
  providers,variables,_,_,db=context(); v=next((x for x in variables if x.id==variable),None)
  if not v: raise click.ClickException(f"Unknown variable '{variable}'")
  start=parse_since(since); finish=date.fromisoformat(end) if end else date.today(); rows=history(v,providers,db,start,finish)
  payload={'variable':v.id,'observations':[{'date':o.date,'value':o.value,'source':o.source,'fetched_at':o.fetched_at} for o in rows]}
  if json_output: emit(payload,True);return
  values=[o.value for o in rows]; summary='No local coverage.' if not rows else f'Coverage: {rows[0].date} to {rows[-1].date}; {len(rows)} points; min={min(values):.4g} max={max(values):.4g} first={values[0]:.4g} last={values[-1]:.4g}'
  emit(summary+'\n'+'\n'.join(f'{o.date}  {o.value:.6g} {v.unit}' for o in rows),False)
 return CommandManifest('history',command)
