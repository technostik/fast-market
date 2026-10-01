from __future__ import annotations
import csv
from datetime import date,datetime,timezone
from io import StringIO
from core.http import get
from plugins.base.plugin import Observation,ProviderDescriptor,ProviderError
def _rows(symbol):
 text=get('https://stooq.com/q/d/l/',params={'s':symbol,'i':'d'})
 if not text or not text.strip(): raise ProviderError(f"Stooq returned empty response for '{symbol}'")
 reader=csv.DictReader(StringIO(text))
 fields=reader.fieldnames or []
 if 'Date' not in fields or 'Close' not in fields:
  raise ProviderError(f"Stooq returned unexpected format for '{symbol}': {text[:200]!r}")
 rows=list(reader)
 if not rows: raise ProviderError(f"Stooq returned no observations for '{symbol}'")
 return rows
class StooqProvider:
  descriptor=ProviderDescriptor('stooq',(),True,'Stooq daily symbol, for example co.f, cl.f, xauusd, or 10yfry.b.')
  def __init__(self,config): pass
  def validate_symbol(self,symbol):
   if not symbol or any(c.isspace() for c in symbol): raise ValueError('symbol must be a non-empty Stooq ticker')
  def fetch_latest(self,symbol): return self._obs(_rows(symbol)[-1],symbol)
  def fetch_history(self,symbol,start,end):
   out=[]
   for r in _rows(symbol):
    try: d=date.fromisoformat(r['Date'])
    except (KeyError,ValueError) as exc: raise ProviderError(f"Stooq returned invalid Date for '{symbol}': {r.get('Date')!r}") from exc
    if start<=d<=end: out.append(self._obs(r,symbol))
   return out
  def _obs(self,row,symbol):
   try: d=date.fromisoformat(row['Date'])
   except (KeyError,ValueError) as exc: raise ProviderError(f"Stooq returned invalid Date for '{symbol}': {row.get('Date')!r}") from exc
   try: v=float(row['Close'])
   except (KeyError,TypeError,ValueError) as exc: raise ProviderError(f"Stooq returned invalid Close for '{symbol}': {row.get('Close')!r}") from exc
   return Observation('',d,v,'','stooq',datetime.now(timezone.utc))
