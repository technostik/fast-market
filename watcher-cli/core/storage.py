from __future__ import annotations
import sqlite3
from datetime import date, datetime, timezone
from common.core.paths import get_tool_data_dir
from plugins.base.plugin import Observation
def connection(path=None):
 p=path or get_tool_data_dir('watcher')/'watcher.sqlite3'; p.parent.mkdir(parents=True,exist_ok=True); db=sqlite3.connect(p); db.execute('CREATE TABLE IF NOT EXISTS observations (variable_id TEXT NOT NULL, date TEXT NOT NULL, value REAL NOT NULL, source TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY(variable_id,date))'); return db
def upsert(db, obs:Observation): db.execute('INSERT INTO observations VALUES(?,?,?,?,?) ON CONFLICT(variable_id,date) DO UPDATE SET value=excluded.value,source=excluded.source,fetched_at=excluded.fetched_at',(obs.variable_id,obs.date.isoformat(),obs.value,obs.source,obs.fetched_at.isoformat())); db.commit()
def observations(db,variable_id,start=None,end=None):
 q='SELECT date,value,source,fetched_at FROM observations WHERE variable_id=?'; args=[variable_id]
 if start: q+=' AND date>=?';args.append(start.isoformat())
 if end:q+=' AND date<=?';args.append(end.isoformat())
 q+=' ORDER BY date'; return [Observation(variable_id,date.fromisoformat(d),v,'',s,datetime.fromisoformat(f)) for d,v,s,f in db.execute(q,args)]
