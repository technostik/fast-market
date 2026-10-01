from __future__ import annotations
import csv
from datetime import date,datetime,timezone
from io import StringIO
from core.http import get
from plugins.base.plugin import Observation,ProviderDescriptor,ProviderError
def _column(symbol):
 dataset=symbol.split('.')[0]
 text=get(f'https://webstat.banque-france.fr/export/csv-columns/fr/catalog/{dataset}')
 rows=list(csv.reader(StringIO(text),delimiter=';'))
 header=None
 for i,r in enumerate(rows):
  if r and r[0].strip().lower().startswith('code série'): header=(i,r); break
 if header is None: raise ProviderError(f'BdF returned unexpected format for {symbol!r}: {text[:200]!r}')
 _,hdr=header
 if symbol not in hdr: raise ProviderError(f'BdF catalog {dataset!r} has no series {symbol!r}')
 col=hdr.index(symbol); points=[]
 for r in rows[header[0]+1:]:
  if not r or len(r)<=col: continue
  try: d=date.fromisoformat(r[0].strip())
  except ValueError: continue
  raw=r[col].strip().replace(',','.')
  if not raw: continue
  try: v=float(raw)
  except ValueError: continue
  points.append((d,v))
 if not points: raise ProviderError(f'BdF returned no observations for {symbol!r}')
 points.sort()
 return points
class BdfProvider:
 descriptor=ProviderDescriptor('bdf',(),True,'Banque de France Webstat series, for example FM.D.FR.EUR.FR2.BB.FRMOYTEC10.HSTA (France TEC10 daily).')
 def __init__(self,config): pass
 def validate_symbol(self,symbol):
  if not symbol or any(c.isspace() for c in symbol): raise ValueError('symbol must be a BdF SDMX series code, for example FM.D.FR.EUR.FR2.BB.FRMOYTEC10.HSTA')
  if '.' not in symbol: raise ValueError('symbol must be a BdF SDMX series code starting with its dataset, for example FM.D.FR.EUR.FR2.BB.FRMOYTEC10.HSTA')
 def fetch_latest(self,symbol):
  d,v=_column(symbol)[-1]; return Observation('',d,v,'','bdf',datetime.now(timezone.utc))
 def fetch_history(self,symbol,start,end):
  return [Observation('',d,v,'','bdf',datetime.now(timezone.utc)) for d,v in _column(symbol) if start<=d<=end]
