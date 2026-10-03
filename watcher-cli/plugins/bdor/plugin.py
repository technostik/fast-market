from __future__ import annotations
import re
from datetime import date,datetime,timezone
from core.http import get
from plugins.base.plugin import Observation,ProviderDescriptor,ProviderError
_PAGE='https://www.bdor.fr/cours-or'
def _page():
 try: text=get(_PAGE)
 except Exception as exc: raise ProviderError(f'BdOR request failed: {exc}') from exc
 if 'prixAffiche' not in text or 'Actualisation' not in text:
  raise ProviderError(f'BdOR returned unexpected format: {text[:200]!r}')
 return text
def _asof(text):
 m=re.search(r'Actualisation[^0-9]*(\d{2})/(\d{2})/(\d{4})',text)
 if not m: raise ProviderError('BdOR returned no fixing date')
 try: return date(int(m.group(3)),int(m.group(2)),int(m.group(1)))
 except ValueError as exc: raise ProviderError(f'BdOR returned invalid fixing date: {m.group(0)!r}') from exc
def _price(text,symbol):
 i=text.find(symbol)
 if i<0: raise ProviderError(f'BdOR has no product {symbol!r}')
 m=re.search(r'prixAffiche\">\s*([\d\s]+,\d+)\s*€',text[i:i+2000])
 if not m: raise ProviderError(f'BdOR returned no price for {symbol!r}')
 try: return float(m.group(1).replace(' ','').replace('\u202f','').replace(',','.'))
 except ValueError as exc: raise ProviderError(f'BdOR returned invalid price for {symbol!r}: {m.group(1)!r}') from exc
class BdorProvider:
 descriptor=ProviderDescriptor('bdor',(),True,'BdOR product slug, for example 20-francs-napoleon-or (Napoléon 20F fixing, EUR).')
 def __init__(self,config): pass
 def validate_symbol(self,symbol):
  if not symbol or any(c.isspace() for c in symbol): raise ValueError('symbol must be a BdOR product slug, for example 20-francs-napoleon-or')
 def fetch_latest(self,symbol):
  text=_page()
  return Observation('',_asof(text),_price(text,symbol),'','bdor',datetime.now(timezone.utc))
 def fetch_history(self,symbol,start,end):
  o=self.fetch_latest(symbol)
  return [o] if start<=o.date<=end else []
