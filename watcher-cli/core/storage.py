from __future__ import annotations
import sqlite3
from datetime import date, datetime, timezone
from common.core.paths import get_tool_data_dir
from plugins.base.plugin import Observation
def connection(path=None):
 p=path or get_tool_data_dir('watcher')/'watcher.sqlite3'; p.parent.mkdir(parents=True,exist_ok=True); db=sqlite3.connect(p); db.execute('CREATE TABLE IF NOT EXISTS observations (variable_id TEXT NOT NULL, date TEXT NOT NULL, value REAL NOT NULL, source TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY(variable_id,date))'); db.execute('CREATE TABLE IF NOT EXISTS history_sync (variable_id TEXT PRIMARY KEY, synced_from TEXT NOT NULL, synced_to TEXT NOT NULL, synced_at TEXT NOT NULL)'); return db
def upsert(db, obs:Observation): db.execute('INSERT INTO observations VALUES(?,?,?,?,?) ON CONFLICT(variable_id,date) DO UPDATE SET value=excluded.value,source=excluded.source,fetched_at=excluded.fetched_at',(obs.variable_id,obs.date.isoformat(),obs.value,obs.source,obs.fetched_at.isoformat())); db.commit()
def observations(db,variable_id,start=None,end=None):
 q='SELECT date,value,source,fetched_at FROM observations WHERE variable_id=?'; args=[variable_id]
 if start: q+=' AND date>=?';args.append(start.isoformat())
 if end:q+=' AND date<=?';args.append(end.isoformat())
 q+=' ORDER BY date'; return [Observation(variable_id,date.fromisoformat(d),v,'',s,datetime.fromisoformat(f)) for d,v,s,f in db.execute(q,args)]
# Incremental history bookkeeping (same XDG data-dir sqlite, never config):
# remembers the locally-held coverage per variable plus the date of the last
# successful provider load, so repeat views only fetch missing gaps (or nothing).
def history_bounds(db,variable_id):
 row=db.execute('SELECT MIN(date),MAX(date) FROM observations WHERE variable_id=?',(variable_id,)).fetchone()
 if not row or not row[0]: return None
 return (date.fromisoformat(row[0]),date.fromisoformat(row[1]))
def get_history_sync(db,variable_id):
 row=db.execute('SELECT synced_from,synced_to,synced_at FROM history_sync WHERE variable_id=?',(variable_id,)).fetchone()
 if not row: return None
 try: at=datetime.fromisoformat(row[2])
 except ValueError: return None
 if at.tzinfo is None: at=at.replace(tzinfo=timezone.utc)
 return (date.fromisoformat(row[0]),date.fromisoformat(row[1]),at)
def save_history_sync(db,variable_id,synced_from,synced_to,synced_at):
 db.execute('INSERT INTO history_sync VALUES(?,?,?,?) ON CONFLICT(variable_id) DO UPDATE SET synced_from=excluded.synced_from,synced_to=excluded.synced_to,synced_at=excluded.synced_at',(variable_id,synced_from.isoformat(),synced_to.isoformat(),synced_at.isoformat())); db.commit()
