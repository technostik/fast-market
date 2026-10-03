from __future__ import annotations
import calendar
import json
from datetime import date,datetime,timezone
from core.http import get
from plugins.base.plugin import Observation,ProviderDescriptor,ProviderError
_UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
def _chart(symbol,params):
 data=json.loads(get(f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}',params=params,headers=_UA))
 chart=data.get('chart') if isinstance(data,dict) else None
 if not chart: raise ProviderError(f'Yahoo returned unexpected format for {symbol!r}')
 if chart.get('error'): raise ProviderError(f"Yahoo error for {symbol!r}: {chart['error']}")
 try: result=chart['result'][0]
 except (KeyError,TypeError,IndexError) as exc: raise ProviderError(f'Yahoo did not return {symbol!r}') from exc
 return result
class YahooProvider:
 descriptor=ProviderDescriptor('yahoo',(),True,'Yahoo Finance ticker, for example SPCX (SpaceX) or MDE10.AS (Bund 10Y yield).')
 def __init__(self,config): pass
 def validate_symbol(self,symbol):
  if not symbol or any(c.isspace() for c in symbol): raise ValueError('symbol must be a Yahoo Finance ticker, for example SPCX')
 def fetch_latest(self,symbol):
  meta=_chart(symbol,{'range':'5d','interval':'1d'}).get('meta') or {}
  try: value=float(meta['regularMarketPrice'])
  except (KeyError,TypeError,ValueError) as exc: raise ProviderError(f'Yahoo returned no price for {symbol!r}') from exc
  try: d=datetime.fromtimestamp(int(meta.get('regularMarketTime')),tz=timezone.utc).date()
  except (TypeError,ValueError): d=date.today()
  return Observation('',d,value,'','yahoo',datetime.now(timezone.utc))
 def fetch_history(self,symbol,start,end):
  p1=calendar.timegm(start.timetuple()); p2=calendar.timegm(end.timetuple())+86400
  r=_chart(symbol,{'period1':str(p1),'period2':str(p2),'interval':'1d'})
  ts=r.get('timestamp') or []
  try: closes=r['indicators']['quote'][0]['close']
  except (KeyError,TypeError,IndexError): closes=[]
  out=[]
  for t,c in zip(ts,closes):
   if c is None: continue
   d=datetime.fromtimestamp(int(t),tz=timezone.utc).date()
   if start<=d<=end: out.append(Observation('',d,float(c),'','yahoo',datetime.now(timezone.utc)))
  out.sort(key=lambda o:o.date)
  return out
