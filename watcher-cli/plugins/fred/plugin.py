from __future__ import annotations
import json
import os
import re
from datetime import date,datetime,timezone
from core.http import get
from plugins.base.plugin import Observation,ProviderDescriptor,ProviderError
_SERIES=re.compile(r'^[A-Za-z0-9_.-]+$')
def _key():
 key=os.getenv('FRED_API_KEY')
 if not key: raise ProviderError('Missing credentials: set FRED_API_KEY in the watcher .env file.')
 return key
def _observations(symbol,extra):
 try: data=json.loads(get('https://api.stlouisfed.org/fred/series/observations',params={'series_id':symbol,'api_key':_key(),'file_type':'json',**extra}))
 except Exception as exc: raise ProviderError(f'FRED request failed for {symbol!r}: {exc}') from exc
 obs=data.get('observations')
 if not isinstance(obs,list): raise ProviderError(f'FRED returned unexpected format for {symbol!r}: {str(data)[:200]!r}')
 return obs
def _parse(symbol,item):
 try: d=date.fromisoformat(item['date'])
 except (KeyError,ValueError) as exc: raise ProviderError(f'FRED returned invalid date for {symbol!r}: {item.get("date")!r}') from exc
 try: v=float(item['value'])
 except (KeyError,TypeError,ValueError) as exc: raise ProviderError(f'FRED returned non-numeric value for {symbol!r}: {item.get("value")!r}') from exc
 return Observation('',d,v,'','fred',datetime.now(timezone.utc))
class FredProvider:
 descriptor=ProviderDescriptor('fred',('FRED_API_KEY',),True,'FRED series id, for example IRLTLT01FRM156N (France 10Y) or DGS10 (US 10Y).')
 def __init__(self,config): pass
 def validate_symbol(self,symbol):
  if not symbol or not _SERIES.fullmatch(symbol): raise ValueError('symbol must be a FRED series id (letters, numbers, and ._-), for example IRLTLT01FRM156N')
 def fetch_latest(self,symbol):
  obs=[o for o in _observations(symbol,{'sort_order':'desc','limit':5}) if o.get('value') not in (None,'','.')] 
  if not obs: raise ProviderError(f'FRED returned no observations for {symbol!r}')
  return _parse(symbol,obs[0])
 def fetch_history(self,symbol,start,end):
  return [_parse(symbol,o) for o in _observations(symbol,{'sort_order':'asc','observation_start':start.isoformat(),'observation_end':end.isoformat()}) if o.get('value') not in (None,'','.') and start<=date.fromisoformat(o['date'])<=end]
