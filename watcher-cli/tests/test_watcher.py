from datetime import date,datetime,timezone
from pathlib import Path
import pytest
from click.testing import CliRunner
from core.config import load_config
from core.models import Variable
from core.services import dedupe
from core.storage import connection,upsert,observations
from core.models import NewsItem
from core.models import Topic
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
def test_stooq_rejects_unexpected_csv_format(monkeypatch):
 from plugins.stooq.plugin import StooqProvider
 from plugins.base.plugin import ProviderError
 import plugins.stooq.plugin as stooq_mod
 monkeypatch.setattr(stooq_mod,'get',lambda *a,**k: '<html><body>bot check</body></html>\nsecond line\n')
 with pytest.raises(ProviderError,match='unexpected format'):
  StooqProvider({}).fetch_latest('10yfry.b')
 monkeypatch.setattr(stooq_mod,'get',lambda *a,**k: 'No data\n')
 with pytest.raises(ProviderError,match='unexpected format|no observations'):
  StooqProvider({}).fetch_latest('10yfry.b')
def test_stooq_parses_valid_daily_csv(monkeypatch):
 from plugins.stooq.plugin import StooqProvider
 import plugins.stooq.plugin as stooq_mod
 monkeypatch.setattr(stooq_mod,'get',lambda *a,**k: 'Date,Open,High,Low,Close,Volume\n2026-09-29,4.70,4.77,4.69,4.762,0\n2026-09-30,4.76,4.80,4.75,4.781,0\n')
 obs=StooqProvider({}).fetch_latest('10yfry.b')
 assert str(obs.date)=='2026-09-30' and obs.value==pytest.approx(4.781)
def test_catalog_oat_uses_daily_bdf():
 import yaml
 catalog=yaml.safe_load((Path(__file__).resolve().parents[1]/'catalog.yaml').read_text())
 oat=next(v for v in catalog['variables'] if v['id']=='oat_10y')
 assert oat['provider']=='bdf' and oat['symbol']=='FM.D.FR.EUR.FR2.BB.FRMOYTEC10.HSTA'
def test_bdf_parses_decimal_comma_newest_first(monkeypatch):
 from plugins.bdf.plugin import BdfProvider
 import plugins.bdf.plugin as bdf_mod
 csv_text=('Titre :;TEC10\nCode série :;FM.D.FR.EUR.FR2.BB.FRMOYTEC10.HSTA\n'
  'Magnitude :;Unités (0)\n2026-12-31;\n2026-10-01;4,903\n2026-09-30;4,751\n2026-09-29;\n')
 monkeypatch.setattr(bdf_mod,'get',lambda *a,**k: csv_text)
 obs=BdfProvider({}).fetch_latest('FM.D.FR.EUR.FR2.BB.FRMOYTEC10.HSTA')
 assert str(obs.date)=='2026-10-01' and obs.value==pytest.approx(4.903) and obs.source=='bdf'
 hist=BdfProvider({}).fetch_history('FM.D.FR.EUR.FR2.BB.FRMOYTEC10.HSTA',date(2026,9,30),date(2026,10,1))
 assert [(str(o.date),o.value) for o in hist]==[('2026-09-30',4.751),('2026-10-01',4.903)]
def test_bdf_rejects_unknown_series(monkeypatch):
 from plugins.bdf.plugin import BdfProvider
 from plugins.base.plugin import ProviderError
 import plugins.bdf.plugin as bdf_mod
 monkeypatch.setattr(bdf_mod,'get',lambda *a,**k: 'Titre :;X\nCode série :;FM.OTHER\n2026-10-01;1,0\n')
 with pytest.raises(ProviderError,match='no series'):
  BdfProvider({}).fetch_latest('FM.D.FR.EUR.FR2.BB.FRMOYTEC10.HSTA')
 with pytest.raises(ValueError): BdfProvider({}).validate_symbol('has space')
def test_dbnomics_skips_na_strings(monkeypatch):
 import json
 from plugins.dbnomics.plugin import DBnomicsProvider
 import plugins.dbnomics.plugin as dbn_mod
 payload={'series':{'docs':[{'period':['2026-06-13','2026-06-14','2026-06-16'],'value':['NA','NA',3.65]}]}}
 monkeypatch.setattr(dbn_mod,'get',lambda *a,**k: json.dumps(payload))
 obs=DBnomicsProvider({}).fetch_latest('BDF/FM/D.FR.EUR.FR2.BB.FRMOYTEC10.HSTA')
 assert str(obs.date)=='2026-06-16' and obs.value==pytest.approx(3.65)
def test_fred_fetch_latest_skips_missing_values(monkeypatch):
 import json
 from plugins.fred.plugin import FredProvider
 import plugins.fred.plugin as fred_mod
 monkeypatch.setenv('FRED_API_KEY','test-key')
 monkeypatch.setattr(fred_mod,'get',lambda *a,**k: json.dumps({'observations':[{'date':'2026-06-01','value':'.'},{'date':'2026-05-01','value':'3.74'}]}))
 obs=FredProvider({}).fetch_latest('IRLTLT01FRM156N')
 assert str(obs.date)=='2026-05-01' and obs.value==pytest.approx(3.74) and obs.source=='fred'
def test_fred_no_observations_is_provider_error(monkeypatch):
 import json
 from plugins.fred.plugin import FredProvider
 from plugins.base.plugin import ProviderError
 import plugins.fred.plugin as fred_mod
 monkeypatch.setenv('FRED_API_KEY','test-key')
 monkeypatch.setattr(fred_mod,'get',lambda *a,**k: json.dumps({'observations':[]}))
 with pytest.raises(ProviderError,match='no observations'):
  FredProvider({}).fetch_latest('IRLTLT01FRM156N')
 monkeypatch.setattr(fred_mod,'get',lambda *a,**k: json.dumps({'error':'bad key'}))
 with pytest.raises(ProviderError,match='unexpected format'):
  FredProvider({}).fetch_latest('IRLTLT01FRM156N')
def test_fred_requires_api_key(monkeypatch):
 from plugins.fred.plugin import FredProvider
 from plugins.base.plugin import ProviderError
 monkeypatch.delenv('FRED_API_KEY',raising=False)
 with pytest.raises(ProviderError,match='FRED_API_KEY'):
  FredProvider({}).fetch_latest('IRLTLT01FRM156N')
 assert FredProvider.descriptor.required_env==('FRED_API_KEY',)
def test_fred_rejects_bad_symbol():
 from plugins.fred.plugin import FredProvider
 with pytest.raises(ValueError): FredProvider({}).validate_symbol('has space')
 with pytest.raises(ValueError): FredProvider({}).validate_symbol('')
 FredProvider({}).validate_symbol('IRLTLT01FRM156N')
def test_dashboard_last_and_nolinks(monkeypatch):
 from datetime import timedelta
 from click.testing import CliRunner
 import commands.dashboard.register as dash_mod
 items=[NewsItem('t',f'Title {n}','Src {n}',datetime(2026,9,30,12,0,tzinfo=timezone.utc)-timedelta(hours=n),f'https://x/{n}') for n in range(5)]
 class News:
  def fetch(self,topic): return list(items)
 monkeypatch.setattr(dash_mod,'context',lambda: ({'google_news':News()},[],[Topic('t','T','q','en')],[],None))
 cmd=dash_mod.register({}).click_command
 out=CliRunner().invoke(cmd,[]).output
 assert 'Title 0' in out and 'Title 2' in out and 'Title 3' not in out and 'https://x/0' in out
 out=CliRunner().invoke(cmd,['--last','2']).output
 assert 'Title 1' in out and 'Title 2' not in out
 out=CliRunner().invoke(cmd,['--nolinks']).output
 assert 'Title 0' in out and 'https://' not in out
 out=CliRunner().invoke(cmd,['--last','0']).output
 assert 'Title 0' not in out
def test_human_results_full_precision_percent():
 from datetime import date
 from commands.helpers import human_results
 from core.models import VariableResult
 r=VariableResult('oat_10y','OAT',3.68,'percent',date(2026,8,1),'fred',0.06,1.66,False,None)
 line=[l for l in human_results([r]).splitlines() if l.startswith('oat_10y')][0]
 assert '3.68%' in line and 'percent' not in line
 r2=VariableResult('gold','Gold',2648.125,'USD/oz',date(2026,9,30),'stooq',None,None,False,None)
 line2=[l for l in human_results([r2]).splitlines() if l.startswith('gold')][0]
 assert '2648.125 USD/oz' in line2
