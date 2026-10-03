from __future__ import annotations
from dataclasses import replace
from datetime import date,datetime,timezone,timedelta
from core.models import NewsItem,Variable,VariableResult
from core.storage import observations,upsert
# Dual EUR/USD display: converted from the `eurusd` variable (USD per EUR,
# read from storage so no extra fetch is needed). Units not
# listed here (percent, USD/EUR, …) have no meaningful conversion.
def _secondary(unit,value,rate):
 if value is None or not rate or rate<=0: return (None,None)
 if unit=='EUR': return (value*rate,'USD')
 if unit=='USD': return (value/rate,'EUR')
 if unit=='USD/bbl': return (value/rate,'EUR/bbl')
 if unit=='USD/oz': return (value/rate,'EUR/oz')
 if unit=='EUR/bbl': return (value*rate,'USD/bbl')
 if unit=='EUR/oz': return (value*rate,'USD/oz')
 return (None,None)
# Values fetched less than an hour ago are served from storage without
# hitting providers again; pass force=True for an explicit refresh.
_FRESH_SECONDS=3600
def _fresh(obs,now):
 fa=obs.fetched_at
 if fa is None: return False
 if fa.tzinfo is None: fa=fa.replace(tzinfo=timezone.utc)
 return (now-fa).total_seconds()<_FRESH_SECONDS
def latest(variables,providers,db,force=False):
 results=[]
 now=datetime.now(timezone.utc)
 for v in variables:
  try: rows=observations(db,v.id)[-2:]
  except Exception: rows=[]
  if not force and rows and _fresh(rows[-1],now):
   c=rows[-1]; prior=None
   for r in reversed(rows[:-1]):
    if r.date != c.date: prior=r; break
   change=None if not prior else c.value-prior.value
   results.append(VariableResult(v.id,v.label,c.value,v.unit,c.date,c.source,change,None if not prior or prior.value==0 else change/prior.value*100,(date.today()-c.date).days>v.max_age_days,None,icon=v.icon))
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
   change=None if not prior else o.value-prior.value
   results.append(VariableResult(v.id,v.label,o.value,v.unit,o.date,o.source,change,None if not prior or prior.value==0 else change/prior.value*100,(date.today()-o.date).days>v.max_age_days,None,icon=v.icon))
  except Exception as exc:
   if rows:
    c=rows[-1]; prior=None
    for r in reversed(rows[:-1]):
     if r.date != c.date: prior=r; break
    change=None if not prior else c.value-prior.value
    results.append(VariableResult(v.id,v.label,c.value,v.unit,c.date,c.source,change,None if not prior or prior.value==0 else change/prior.value*100,True,str(exc),icon=v.icon))
   else: results.append(VariableResult(v.id,v.label,None,v.unit,None,v.provider,None,None,False,str(exc)))
 try: fx=observations(db,'eurusd')[-1:]
 except Exception: fx=[]
 rate=fx[-1].value if fx else None
 if rate and rate>0:
  out=[]
  for r in results:
   sv,su=_secondary(r.unit,r.value,rate)
   out.append(replace(r,secondary_value=sv,secondary_unit=su) if sv is not None else r)
  results=out
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
