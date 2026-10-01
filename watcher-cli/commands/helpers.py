from __future__ import annotations
import json
from dataclasses import asdict
from datetime import date,datetime,timezone,timedelta
import click
from core.config import load_config,load_env
from core.storage import connection
from core.services import latest,dedupe
from common.core.registry import build_plugins
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def context():
 load_env(); providers=build_plugins({},tool_root=ROOT)
 try: variables,topics,feeds=load_config(providers)
 except ValueError as exc: raise click.ClickException(str(exc)) from exc
 return providers,variables,topics,feeds,connection()
def iso(value): return value.isoformat() if hasattr(value,'isoformat') else value
def emit(data,json_output):
 if json_output: click.echo(json.dumps(data,default=iso,sort_keys=True))
 else: click.echo(data if isinstance(data,str) else json.dumps(data,default=iso,indent=2))
def results_payload(results): return {'generated_at':datetime.now(timezone.utc).isoformat(),'variables':[asdict(x) for x in results]}
def human_results(results):
 lines=['ID        VALUE             CHANGE          AS OF       SOURCE']
 for r in results:
  if r.error: lines.append(f'{r.id:<10} ERROR: {r.error}')
  else:
   unit='%' if r.unit=='percent' else f' {r.unit}'
   change='—' if r.change_abs is None else f'{round(r.change_abs,6):+} ({r.change_pct:+.2f}%)'; stale=' STALE' if r.stale else ''
   lines.append(f'{r.id:<10} {f"{r.value!r}{unit}":<18} {change:<17} {r.as_of} {r.source}{stale}')
 return '\n'.join(lines)
def parse_since(text):
 import re
 m=re.fullmatch(r'(\d+)([dhmy])',text)
 if not m: raise click.BadParameter('must be a duration such as 24h, 6m, or 1y')
 return date.today()-timedelta(days=int(m.group(1))*{'h':1/24,'d':1,'m':30,'y':365}[m.group(2)])
