from __future__ import annotations
from datetime import date,datetime,timezone
from core.http import get
from plugins.base.plugin import Observation,ProviderDescriptor,ProviderError
class DBnomicsProvider:
 descriptor=ProviderDescriptor('dbnomics',(),True,'PROVIDER/DATASET/SERIES, for example IMF/IFS/M.FR.FI_10Y')
 def __init__(self,config): pass
 def validate_symbol(self,s):
  if len(s.split('/'))!=3: raise ValueError('symbol must be PROVIDER/DATASET/SERIES')
 def _series(self,s):
  data=__import__('json').loads(get('https://api.db.nomics.world/v22/series/'+s,params={'observations':'1'})); docs=data.get('series',{}).get('docs',[])
  if not docs: raise ProviderError('DBnomics returned no series')
  return docs[0]
 def _obs(self,s):
  d=self._series(s); periods=d.get('period',[]); values=d.get('value',[]); pairs=[(p,v) for p,v in zip(periods,values) if v is not None]
  return [Observation('',date.fromisoformat(p[:10]+'-01' if len(p)==7 else p),float(v),'','dbnomics',datetime.now(timezone.utc)) for p,v in pairs]
 def fetch_latest(self,s): return self._obs(s)[-1]
 def fetch_history(self,s,start,end): return [o for o in self._obs(s) if start<=o.date<=end]
 def search(self,query):
  data=__import__('json').loads(get('https://api.db.nomics.world/v22/series/'+query)); return data
