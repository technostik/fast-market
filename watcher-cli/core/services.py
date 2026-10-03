from __future__ import annotations
from datetime import date,datetime,timezone,timedelta
from core.models import NewsItem,Variable,VariableResult
from core.storage import observations,upsert
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
