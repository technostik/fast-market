from __future__ import annotations
import json
from datetime import date,datetime,timezone
from core.http import get
from plugins.base.plugin import Observation,ProviderDescriptor,ProviderError
def _quote(symbol):
 data=json.loads(get('https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol',params={'symbols':symbol,'requestMethod':'quick','noform':'1','partnerId':'2','fund':'1','exthrs':'1','output':'json'}))
 try: q=data['FormattedQuoteResult']['FormattedQuote'][0]
 except (KeyError,TypeError,IndexError) as exc: raise ProviderError(f'CNBC did not return {symbol!r}') from exc
 if q.get('code') not in (0,'0',None): raise ProviderError(f"CNBC error for {symbol!r}: {q.get('code')}")
 return q
def _parse(symbol,q):
 try: value=float(str(q['last']).strip().rstrip('%'))
 except (KeyError,TypeError,ValueError) as exc: raise ProviderError(f"CNBC returned no price for {symbol!r}: {q.get('last')!r}") from exc
 try: d=date.fromisoformat(str(q.get('last_time'))[:10])
 except (TypeError,ValueError): d=date.today()
 return Observation('',d,value,'','cnbc',datetime.now(timezone.utc))
class CnbcProvider:
 descriptor=ProviderDescriptor('cnbc',(),True,'CNBC bond quote symbol, for example GB10Y (UK 10Y gilt).')
 def __init__(self,config): pass
 def validate_symbol(self,symbol):
  if not symbol or any(c.isspace() for c in symbol): raise ValueError('symbol must be a CNBC quote symbol, for example GB10Y')
 def fetch_latest(self,symbol): return _parse(symbol,_quote(symbol))
 def fetch_history(self,symbol,start,end):
  o=self.fetch_latest(symbol)
  return [o] if start<=o.date<=end else []
