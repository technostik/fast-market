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
def latest(variables,providers,db):
 results=[]
 for v in variables:
  try:
   p=providers[v.provider]
   for env in p.descriptor.required_env:
    import os
    if not os.getenv(env): raise __import__('plugins.base.plugin',fromlist=['MissingCredentialsError']).MissingCredentialsError(env)
   o=p.fetch_latest(v.symbol); o=type(o)(v.id,o.date,o.value,v.unit,o.source,o.fetched_at); rows=observations(db,v.id)[-2:] ; upsert(db,o)
   prior=None
   for r in reversed(rows):
    if r.date != o.date: prior=r; break
   change=None if not prior else o.value-prior.value
   results.append(VariableResult(v.id,v.label,o.value,v.unit,o.date,o.source,change,None if not prior or prior.value==0 else change/prior.value*100,(date.today()-o.date).days>v.max_age_days,None))
  except Exception as exc:
   try: rows=observations(db,v.id)[-2:]
   except Exception: rows=[]
   if rows:
    c=rows[-1]; prior=None
    for r in reversed(rows[:-1]):
     if r.date != c.date: prior=r; break
    change=None if not prior else c.value-prior.value
    results.append(VariableResult(v.id,v.label,c.value,v.unit,c.date,c.source,change,None if not prior or prior.value==0 else change/prior.value*100,True,str(exc)))
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
