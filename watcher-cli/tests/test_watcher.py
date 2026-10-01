from datetime import date,datetime,timezone
from pathlib import Path
import pytest
from click.testing import CliRunner
from core.config import load_config
from core.models import Variable
from core.services import dedupe
from core.storage import connection,upsert,observations
from core.models import NewsItem
from plugins.base.plugin import Observation
class Provider:
 def validate_symbol(self,s):
  if s=='bad': raise ValueError('bad symbol')
def test_config_rejects_unknown_key_and_dangling_topic(tmp_path):
 path=tmp_path/'watcher.yaml'; path.write_text('version: 1\nvariables: []\nnews_topics: []\nfeeds: []\nunexpected: true\n')
 with pytest.raises(ValueError,match='unexpected'): load_config({'test':Provider()},path)
 path.write_text('version: 1\nvariables: [{id: x, label: X, provider: test, symbol: ok, unit: x, news_topics: [missing]}]\nnews_topics: []\nfeeds: []\n')
 with pytest.raises(ValueError,match='unknown news topic'): load_config({'test':Provider()},path)
def test_second_variable_needs_yaml_only(tmp_path):
 path=tmp_path/'watcher.yaml';path.write_text('version: 1\nvariables: [{id: one, label: One, provider: test, symbol: ok, unit: x}, {id: two, label: Two, provider: test, symbol: ok, unit: x}]\nnews_topics: []\nfeeds: []\n')
 variables,_,_=load_config({'test':Provider()},path); assert [v.id for v in variables]==['one','two']
def test_upsert_is_idempotent(tmp_path):
 db=connection(tmp_path/'watcher.sqlite3'); o=Observation('gold',date(2026,1,1),1.0,'USD/oz','fake',datetime.now(timezone.utc));upsert(db,o);upsert(db,Observation('gold',o.date,2.0,o.unit,o.source,o.fetched_at)); rows=observations(db,'gold');assert len(rows)==1 and rows[0].value==2.0
def test_news_dedupe_url_then_title():
 now=datetime.now(timezone.utc); items=[NewsItem('x','Same','A',now,'https://x/a?z=1'),NewsItem('x','Other','A',now,'https://x/a?z=2'),NewsItem('x','Same','A',now,'')]; assert len(dedupe(items))==2
def test_missing_credentials_is_a_per_variable_error(tmp_path, monkeypatch):
 from plugins.base.plugin import ProviderDescriptor
 from core.services import latest
 class Keyed:
  descriptor=ProviderDescriptor('keyed',('TEST_WATCHER_KEY',),True,'x')
  def fetch_latest(self, symbol): raise AssertionError('must not fetch without credentials')
 v=Variable('protected','Protected','keyed','x','x',1,())
 result=latest([v],{'keyed':Keyed()},connection(tmp_path/'credentials.sqlite3'))
 assert result[0].value is None and 'TEST_WATCHER_KEY' in result[0].error
