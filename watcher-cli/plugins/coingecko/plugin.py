from __future__ import annotations
from datetime import date,datetime,timezone
from core.http import get
from plugins.base.plugin import Observation,ProviderDescriptor,ProviderError
class CoinGeckoProvider:
 descriptor=ProviderDescriptor('coingecko',(),True,'coin:currency, for example bitcoin:eur')
 def __init__(self,config): pass
 def validate_symbol(self,s):
  if s.count(':')!=1 or not all(s.split(':')): raise ValueError('symbol must be coin:currency, for example bitcoin:eur')
 def fetch_latest(self,s):
  coin,currency=s.split(':'); data=__import__('json').loads(get('https://api.coingecko.com/api/v3/simple/price',params={'ids':coin,'vs_currencies':currency,'include_last_updated_at':'true'})); value=data.get(coin,{}).get(currency)
  if value is None: raise ProviderError(f'CoinGecko did not return {s}')
  stamp=data[coin].get('last_updated_at'); return Observation('',datetime.fromtimestamp(stamp,tz=timezone.utc).date() if stamp else date.today(),float(value),'','coingecko',datetime.now(timezone.utc))
 def fetch_history(self,s,start,end):
  coin,currency=s.split(':'); days=max(1,(end-start).days+1); data=__import__('json').loads(get(f'https://api.coingecko.com/api/v3/coins/{coin}/market_chart',params={'vs_currency':currency,'days':days,'interval':'daily'}))
  return [Observation('',datetime.fromtimestamp(ts/1000,tz=timezone.utc).date(),float(value),'','coingecko',datetime.now(timezone.utc)) for ts,value in data.get('prices',[]) if start<=datetime.fromtimestamp(ts/1000,tz=timezone.utc).date()<=end]
