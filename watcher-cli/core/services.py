from __future__ import annotations
from datetime import date,datetime,timezone,timedelta
from core.models import NewsItem,Variable,VariableResult
from core.storage import observations,upsert
# Consistent main/secondary currency display (default main USD, secondary EUR):
# monetary values are normalized to `main` with the `eurusd` rate (USD per EUR,
# read from storage so no extra fetch is needed); the other currency is shown
# as secondary. Units without a plain EUR/USD base (percent, USD/EUR, …) pass through.
def _main(unit,value,rate,main):
 if value is None or main not in ('EUR','USD'): return (value,unit)
 parts=unit.split('/',1); cur=parts[0]; suf='/'+parts[1] if len(parts)>1 else ''
 if cur not in ('EUR','USD') or suf not in ('','/bbl','/oz'): return (value,unit)
 if cur==main or not rate or rate<=0: return (value,unit)
 if main=='USD': return (value*rate,'USD'+suf)
 return (value/rate,'EUR'+suf)
def _result(v,o,prior,rate,main,other,stale,error):
 mv,mu=_main(v.unit,o.value,rate,main)
 pv,_=_main(v.unit,prior.value,rate,main) if prior is not None else (None,None)
 change=None if pv is None else mv-pv
 sv,su=_main(v.unit,o.value,rate,other)
 if su==mu: sv,su=None,None
 return VariableResult(v.id,v.label,mv,mu,o.date,o.source,change,None if pv is None or pv==0 else change/pv*100,stale,error,sv,su,icon=v.icon)
# Values fetched less than an hour ago are served from storage without
# hitting providers again; pass force=True for an explicit refresh.
_FRESH_SECONDS=3600
def _fresh(obs,now):
 fa=obs.fetched_at
 if fa is None: return False
 if fa.tzinfo is None: fa=fa.replace(tzinfo=timezone.utc)
 return (now-fa).total_seconds()<_FRESH_SECONDS
def latest(variables,providers,db,force=False,main_currency='USD'):
 results=[]
 now=datetime.now(timezone.utc)
 main=main_currency if main_currency in ('EUR','USD') else 'USD'
 other='EUR' if main=='USD' else 'USD'
 try: fx=observations(db,'eurusd')[-1:]
 except Exception: fx=[]
 rate=fx[-1].value if fx else None
 for v in variables:
  try: rows=observations(db,v.id)[-2:]
  except Exception: rows=[]
  if not force and rows and _fresh(rows[-1],now):
   c=rows[-1]; prior=None
   for r in reversed(rows[:-1]):
    if r.date != c.date: prior=r; break
   results.append(_result(v,c,prior,rate,main,other,(date.today()-c.date).days>v.max_age_days,None))
   continue
  try:
   p=providers[v.provider]
   for env in p.descriptor.required_env:
    import os
    if not os.getenv(env): raise __import__('plugins.base.plugin',fromlist=['MissingCredentialsError']).MissingCredentialsError(env)
   o=p.fetch_latest(v.symbol); o=type(o)(v.id,o.date,o.value,v.unit,o.source,o.fetched_at); upsert(db,o)
   prior=None
   for r in reversed(rows):
    if r.date != o.date: prior=r; break
   results.append(_result(v,o,prior,rate,main,other,(date.today()-o.date).days>v.max_age_days,None))
  except Exception as exc:
   if rows:
    c=rows[-1]; prior=None
    for r in reversed(rows[:-1]):
     if r.date != c.date: prior=r; break
    results.append(_result(v,c,prior,rate,main,other,True,str(exc)))
   else: results.append(VariableResult(v.id,v.label,None,v.unit,None,v.provider,None,None,False,str(exc),icon=v.icon))
 return results
def history(v,providers,db,start,end):
 cached=observations(db,v.id,start,end)
 if not cached:
  try:
   for o in providers[v.provider].fetch_history(v.symbol,start,end): upsert(db,type(o)(v.id,o.date,o.value,v.unit,o.source,o.fetched_at))
  except Exception: pass
 return observations(db,v.id,start,end)
def dedupe(items):
 seen=set(); out=[]
 for i in sorted(items,key=lambda x:x.published_at or datetime.min.replace(tzinfo=timezone.utc),reverse=True):
  key=(i.url or '').lower().split('?')[0] or i.title.strip().lower()
  if key not in seen: seen.add(key);out.append(i)
 return out
