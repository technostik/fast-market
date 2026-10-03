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
def test_catalog_oil_uses_fred_and_bitcoin_kraken():
 import yaml
 catalog=yaml.safe_load((Path(__file__).resolve().parents[1]/'catalog.yaml').read_text())
 by_id={v['id']:v for v in catalog['variables']}
 assert by_id['brent']['provider']=='fred' and by_id['brent']['symbol']=='DCOILBRENTEU'
 assert by_id['wti']['provider']=='fred' and by_id['wti']['symbol']=='DCOILWTICO'
 assert by_id['bitcoin']['provider']=='kraken' and by_id['bitcoin']['symbol']=='bitcoin:eur'
 assert 'bitcoin_usd' not in by_id
def test_catalog_spacex_and_eurusd():
 import yaml
 catalog=yaml.safe_load((Path(__file__).resolve().parents[1]/'catalog.yaml').read_text())
 by_id={v['id']:v for v in catalog['variables']}
 assert by_id['spacex']['provider']=='yahoo' and by_id['spacex']['symbol']=='SPCX' and by_id['spacex']['unit']=='USD'
 assert by_id['eurusd']['provider']=='yahoo' and by_id['eurusd']['symbol']=='EURUSD=X'
 topics={t['id'] for t in catalog['news_topics']}
 assert {'spacex_spcx','eur_usd_fx'} <= topics
 for vid in ('spacex','eurusd'):
  for t in by_id[vid]['news_topics']: assert t in topics
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
 assert '2.65K USD/oz' in line2 and '2648' not in line2 and '2648.125' not in line2
def test_news_variable_filter(monkeypatch):
 import json
 import commands.news.register as news_mod
 from core.models import Variable as Var
 items=[NewsItem('bitcoin_regulation','BTC up','CoinDesk',datetime(2026,9,30,12,tzinfo=timezone.utc),'https://x/btc'),
  NewsItem('france_debt_ecb','OAT watch','FT',datetime(2026,9,30,11,tzinfo=timezone.utc),'https://x/oat')]
 class News:
  def fetch(self,topic): return [i for i in items if i.topic==topic.id]
 variables=[Var('bitcoin','Bitcoin','coingecko','bitcoin:eur','EUR',1,('bitcoin_regulation',)),Var('oat_10y','OAT','bdf','X','percent',5,('france_debt_ecb',))]
 topics=[Topic('bitcoin_regulation','BTC','bitcoin regulation','en'),Topic('france_debt_ecb','OAT','France debt','en')]
 monkeypatch.setattr(news_mod,'context',lambda: ({'google_news':News()},variables,topics,[],None))
 cmd=news_mod.register({}).click_command
 out=json.loads(CliRunner().invoke(cmd,['--variable','bitcoin','--json']).output)
 assert [n['topic'] for n in out['news']]==['bitcoin_regulation']
 r=CliRunner().invoke(cmd,['--variable','nope'])
 assert r.exit_code!=0 and 'Unknown variable' in r.output
 r=CliRunner().invoke(cmd,['--variable','bitcoin','--topic','bitcoin_regulation'])
 assert r.exit_code!=0 and 'mutually exclusive' in r.output
def test_kraken_parses_ticker_and_falls_back_to_coinbase(monkeypatch):
 import json
 from plugins.kraken.plugin import KrakenProvider
 import plugins.kraken.plugin as kraken_mod
 from plugins.base.plugin import ProviderError
 monkeypatch.setattr(kraken_mod,'get',lambda *a,**k: json.dumps({'error':[],'result':{'XXBTZEUR':{'c':['61234.5','0.01']}}}))
 obs=KrakenProvider({}).fetch_latest('bitcoin:eur')
 assert obs.value==pytest.approx(61234.5) and obs.source=='kraken'
 monkeypatch.setattr(kraken_mod,'get',lambda *a,**k: (_ for _ in ()).throw(ProviderError('Provider rate limit reached')))
 import plugins.coinbase.plugin as coinbase_mod
 monkeypatch.setattr(coinbase_mod,'get',lambda *a,**k: json.dumps({'data':{'base':'BTC','currency':'EUR','amount':'61000.12'}}))
 obs=KrakenProvider({}).fetch_latest('bitcoin:eur')
 assert obs.value==pytest.approx(61000.12) and obs.source=='coinbase'
 with pytest.raises(ValueError): KrakenProvider({}).validate_symbol('bad-symbol')
def test_kraken_history_parses_ohlc(monkeypatch):
 import json
 from plugins.kraken.plugin import KrakenProvider
 import plugins.kraken.plugin as kraken_mod
 payload={'error':[],'result':{'XXBTZUSD':[[1711929600,'67000.1','68000.0','66000.0','67500.0','67200.0','123.4',5000],[1712016000,'67500.0','69000.0','67000.0','68500.0','68000.0','100.0',4000]],'last':1712016000}}
 monkeypatch.setattr(kraken_mod,'get',lambda *a,**k: json.dumps(payload))
 out=KrakenProvider({}).fetch_history('bitcoin:usd',date(2024,1,1),date(2024,12,31))
 assert [o.value for o in out]==pytest.approx([67500.0,68500.0])
def test_coinbase_spot_and_history(monkeypatch):
 import json
 from plugins.coinbase.plugin import CoinbaseProvider
 import plugins.coinbase.plugin as coinbase_mod
 monkeypatch.setattr(coinbase_mod,'get',lambda *a,**k: json.dumps({'data':{'base':'BTC','currency':'USD','amount':'67000.12'}}))
 obs=CoinbaseProvider({}).fetch_latest('bitcoin:usd')
 assert obs.value==pytest.approx(67000.12) and obs.source=='coinbase'
 def fake_get(url,*a,**k):
  assert 'candles' in url
  return json.dumps([[1712016000,67000.0,69000.0,67500.0,68500.0,100.0]])
 monkeypatch.setattr(coinbase_mod,'get',fake_get)
 out=CoinbaseProvider({}).fetch_history('bitcoin:usd',date(2024,1,1),date(2026,12,31))
 assert len(out)==1 and out[0].value==pytest.approx(68500.0)
def test_latest_falls_back_to_cached_on_rate_limit(tmp_path):
 from core.models import Variable as Var
 from core.services import latest
 from plugins.base.plugin import RateLimitError
 v=Var('bitcoin','Bitcoin','kraken','bitcoin:eur','EUR',1,())
 db=connection(tmp_path/'fallback.sqlite3')
 upsert(db,Observation('bitcoin',date(2026,9,30),61000.0,'EUR','kraken',datetime.now(timezone.utc)))
 class Limited:
  from plugins.base.plugin import ProviderDescriptor as PD
  descriptor=PD('kraken',(),True,'x')
  def fetch_latest(self,symbol): raise RateLimitError('Provider rate limit reached')
 res=latest([v],{'kraken':Limited()},db,force=True)
 assert res[0].value==pytest.approx(61000.0) and res[0].as_of==date(2026,9,30)
 assert res[0].stale is True and 'rate limit' in res[0].error.lower()
 assert res[0].source=='kraken'
def test_latest_without_cache_still_reports_error(tmp_path):
 from core.models import Variable as Var
 from core.services import latest
 from plugins.base.plugin import RateLimitError
 v=Var('bitcoin','Bitcoin','kraken','bitcoin:eur','EUR',1,())
 db=connection(tmp_path/'nocache.sqlite3')
 class Limited:
  from plugins.base.plugin import ProviderDescriptor as PD
  descriptor=PD('kraken',(),True,'x')
  def fetch_latest(self,symbol): raise RateLimitError('Provider rate limit reached')
 res=latest([v],{'kraken':Limited()},db)
 assert res[0].value is None and res[0].error is not None
def test_human_results_shows_cached_value_with_warning():
 from commands.helpers import human_results
 from core.models import VariableResult
 r=VariableResult('bitcoin','Bitcoin',61000.0,'EUR',date(2026,9,30),'kraken',None,None,True,'Provider rate limit reached')
 line=[l for l in human_results([r]).splitlines() if l.startswith('bitcoin')][0]
 assert '61.00K' in line and 'WARNING' in line and 'STALE' in line and 'Provider rate limit reached' in line
def test_catalog_sovereign_10y_usa_uk_germany():
 import yaml
 catalog=yaml.safe_load((Path(__file__).resolve().parents[1]/'catalog.yaml').read_text())
 by_id={v['id']:v for v in catalog['variables']}
 assert by_id['us_10y']['provider']=='fred' and by_id['us_10y']['symbol']=='DGS10' and by_id['us_10y']['unit']=='percent'
 assert by_id['uk_10y']['provider']=='cnbc' and by_id['uk_10y']['symbol']=='GB10Y' and by_id['uk_10y']['unit']=='percent'
 assert by_id['de_10y']['provider']=='yahoo' and by_id['de_10y']['symbol']=='MDE10.AS' and by_id['de_10y']['unit']=='percent'
 topics={t['id'] for t in catalog['news_topics']}
 assert {'us_treasury_fed','uk_gilts','german_bunds'} <= topics
 for vid in ('us_10y','uk_10y','de_10y'):
  for t in by_id[vid]['news_topics']: assert t in topics
def test_latest_change_uses_last_distinct_day_on_same_day_refresh(tmp_path):
 from core.models import Variable as Var
 from core.services import latest
 v=Var('us_10y','US 10Y','fred','DGS10','percent',5,())
 db=connection(tmp_path/'changeday.sqlite3')
 upsert(db,Observation('us_10y',date(2026,9,29),4.70,'percent','fred',datetime.now(timezone.utc)))
 upsert(db,Observation('us_10y',date(2026,9,30),4.75,'percent','fred',datetime.now(timezone.utc)))
 class SameDay:
  from plugins.base.plugin import ProviderDescriptor as PD
  descriptor=PD('fred',(),True,'x')
  def fetch_latest(self,symbol): return Observation('',date(2026,9,30),4.80,'','fred',datetime.now(timezone.utc))
 res=latest([v],{'fred':SameDay()},db,force=True)
 assert res[0].change_abs==pytest.approx(0.10) and res[0].change_pct==pytest.approx(0.10/4.70*100)
def test_latest_change_uses_last_day_on_new_day(tmp_path):
 from core.models import Variable as Var
 from core.services import latest
 v=Var('us_10y','US 10Y','fred','DGS10','percent',5,())
 db=connection(tmp_path/'newday.sqlite3')
 upsert(db,Observation('us_10y',date(2026,9,29),4.70,'percent','fred',datetime.now(timezone.utc)))
 upsert(db,Observation('us_10y',date(2026,9,30),4.75,'percent','fred',datetime.now(timezone.utc)))
 class NewDay:
  from plugins.base.plugin import ProviderDescriptor as PD
  descriptor=PD('fred',(),True,'x')
  def fetch_latest(self,symbol): return Observation('',date(2026,10,1),4.90,'','fred',datetime.now(timezone.utc))
 res=latest([v],{'fred':NewDay()},db,force=True)
 assert res[0].change_abs==pytest.approx(0.15) and res[0].change_pct==pytest.approx(0.15/4.75*100)
def test_fallback_change_uses_last_distinct_day(tmp_path):
 from core.models import Variable as Var
 from core.services import latest
 from plugins.base.plugin import RateLimitError
 v=Var('us_10y','US 10Y','fred','DGS10','percent',5,())
 db=connection(tmp_path/'fallbackchange.sqlite3')
 upsert(db,Observation('us_10y',date(2026,9,29),4.70,'percent','fred',datetime.now(timezone.utc)))
 upsert(db,Observation('us_10y',date(2026,9,30),4.75,'percent','fred',datetime.now(timezone.utc)))
 class Limited:
  from plugins.base.plugin import ProviderDescriptor as PD
  descriptor=PD('fred',(),True,'x')
  def fetch_latest(self,symbol): raise RateLimitError('Provider rate limit reached')
 res=latest([v],{'fred':Limited()},db,force=True)
 assert res[0].value==pytest.approx(4.75) and res[0].change_abs==pytest.approx(0.05)
def _live_provider(value,asof):
 from plugins.base.plugin import ProviderDescriptor as PD
 from plugins.base.plugin import Observation as Obs
 class Live:
  descriptor=PD('test',(),True,'x')
  def fetch_latest(self,symbol): return Obs('',asof,value,'','test',datetime.now(timezone.utc))
 return Live()
def test_latest_adds_eur_usd_secondary(tmp_path):
 from core.models import Variable as Var
 from core.services import latest
 db=connection(tmp_path/'dual.sqlite3')
 upsert(db,Observation('eurusd',date(2026,9,30),1.10,'USD/EUR','fred',datetime.now(timezone.utc)))
 variables=[Var('bitcoin','Bitcoin','kraken','bitcoin:eur','EUR',1,()),Var('gold','Gold','stooq','xauusd','USD/oz',5,()),Var('oat_10y','OAT','bdf','X','percent',5,())]
 providers={'kraken':_live_provider(100000.0,date(2026,9,30)),'stooq':_live_provider(2000.0,date(2026,9,30)),'bdf':_live_provider(3.5,date(2026,9,30))}
 by_id={r.id:r for r in latest(variables,providers,db)}
 assert (by_id['bitcoin'].secondary_value,by_id['bitcoin'].secondary_unit)==(pytest.approx(110000.0),'USD')
 assert (by_id['gold'].secondary_value,by_id['gold'].secondary_unit)==(pytest.approx(2000.0/1.10),'EUR/oz')
 assert by_id['oat_10y'].secondary_value is None and by_id['oat_10y'].secondary_unit is None
def test_latest_secondary_skipped_without_fx(tmp_path):
 from core.models import Variable as Var
 from core.services import latest
 db=connection(tmp_path/'nofx.sqlite3')
 res=latest([Var('bitcoin','Bitcoin','kraken','bitcoin:eur','EUR',1,())],{'kraken':_live_provider(100000.0,date(2026,9,30))},db)
 assert res[0].secondary_value is None
def test_get_refresh_option_exists():
 from click.testing import CliRunner
 import commands.get.register as get_mod
 assert '--refresh' in CliRunner().invoke(get_mod.register({}).click_command,['--help']).output
def test_latest_serves_fresh_cache_without_fetch(tmp_path):
 from core.models import Variable as Var
 from core.services import latest
 v=Var('us_10y','US 10Y','fred','DGS10','percent',30,())
 db=connection(tmp_path/'fresh.sqlite3')
 upsert(db,Observation('us_10y',date(2026,9,29),4.70,'percent','fred',datetime.now(timezone.utc)))
 upsert(db,Observation('us_10y',date(2026,9,30),4.75,'percent','fred',datetime.now(timezone.utc)))
 class NeverCall:
  from plugins.base.plugin import ProviderDescriptor as PD
  descriptor=PD('fred',(),True,'x')
  def fetch_latest(self,symbol): raise AssertionError('must not fetch within 1h')
 res=latest([v],{'fred':NeverCall()},db)
 assert res[0].value==pytest.approx(4.75) and res[0].error is None
 assert res[0].change_abs==pytest.approx(0.05)
def test_latest_force_refresh_bypasses_fresh_cache(tmp_path):
 from core.models import Variable as Var
 from core.services import latest
 v=Var('us_10y','US 10Y','fred','DGS10','percent',30,())
 db=connection(tmp_path/'force.sqlite3')
 upsert(db,Observation('us_10y',date(2026,9,29),4.70,'percent','fred',datetime.now(timezone.utc)))
 upsert(db,Observation('us_10y',date(2026,9,30),4.75,'percent','fred',datetime.now(timezone.utc)))
 class NewDay:
  from plugins.base.plugin import ProviderDescriptor as PD
  descriptor=PD('fred',(),True,'x')
  def fetch_latest(self,symbol): return Observation('',date(2026,10,1),4.90,'','fred',datetime.now(timezone.utc))
 res=latest([v],{'fred':NewDay()},db,force=True)
 assert res[0].value==pytest.approx(4.90) and res[0].change_abs==pytest.approx(0.15)
def test_dashboard_refresh_option_uses_cache_then_forces(monkeypatch,tmp_path):
 import commands.dashboard.register as dash_mod
 from core.models import Variable as Var
 calls=[]
 class P:
  from plugins.base.plugin import ProviderDescriptor as PD
  descriptor=PD('test',(),True,'x')
  def fetch_latest(self,symbol):
   calls.append(1)
   return Observation('',date(2026,10,2),1.0,'','test',datetime.now(timezone.utc))
 v=Var('x','X','test','s','USD',30,())
 db=connection(tmp_path/'dash.sqlite3')
 monkeypatch.setattr(dash_mod,'context',lambda: ({'test':P()},[v],[],[],db))
 cmd=dash_mod.register({}).click_command
 assert CliRunner().invoke(cmd,['--json','--last','0']).exit_code==0 and len(calls)==1
 assert CliRunner().invoke(cmd,['--json','--last','0']).exit_code==0 and len(calls)==1
 assert CliRunner().invoke(cmd,['--json','--last','0','--refresh']).exit_code==0 and len(calls)==2
def test_human_results_shows_secondary():
 from commands.helpers import human_results
 from core.models import VariableResult
 r=VariableResult('bitcoin','Bitcoin',100000.0,'EUR',date(2026,9,30),'kraken',None,None,False,None,110000.0,'USD')
 line=[l for l in human_results([r]).splitlines() if l.startswith('bitcoin')][0]
 assert '100.00K EUR' in line and '(≈110.00K USD)' in line
def test_yahoo_parses_chart_and_history(monkeypatch):
 import json
 from plugins.yahoo.plugin import YahooProvider
 import plugins.yahoo.plugin as yahoo_mod
 from plugins.base.plugin import ProviderError
 payload={'chart':{'result':[{'meta':{'regularMarketPrice':158.96,'regularMarketTime':1790947800},'timestamp':[1790861400,1790947800],'indicators':{'quote':[{'close':[150.5,None]}]}}],'error':None}}
 monkeypatch.setattr(yahoo_mod,'get',lambda *a,**k: json.dumps(payload))
 obs=YahooProvider({}).fetch_latest('SPCX')
 assert obs.value==pytest.approx(158.96) and obs.source=='yahoo' and str(obs.date)=='2026-10-02'
 out=YahooProvider({}).fetch_history('SPCX',date(2026,10,1),date(2026,10,3))
 assert [(str(o.date),o.value) for o in out]==[('2026-10-01',150.5)]
 monkeypatch.setattr(yahoo_mod,'get',lambda *a,**k: json.dumps({'chart':{'result':None,'error':{'code':'Not Found'}}}))
 with pytest.raises(ProviderError): YahooProvider({}).fetch_latest('NOPE')
 with pytest.raises(ValueError): YahooProvider({}).validate_symbol('has space')
def test_cnbc_parses_gilt_quote(monkeypatch):
 import json
 from plugins.cnbc.plugin import CnbcProvider
 import plugins.cnbc.plugin as cnbc_mod
 from plugins.base.plugin import ProviderError
 payload={'FormattedQuoteResult':{'FormattedQuote':[{'code':0,'last':'5.377%','last_time':'2026-10-03T09:23:24.000+0000'}]}}
 monkeypatch.setattr(cnbc_mod,'get',lambda *a,**k: json.dumps(payload))
 obs=CnbcProvider({}).fetch_latest('GB10Y')
 assert obs.value==pytest.approx(5.377) and obs.source=='cnbc' and str(obs.date)=='2026-10-03'
 out=CnbcProvider({}).fetch_history('GB10Y',date(2026,10,1),date(2026,10,5))
 assert len(out)==1 and out[0].value==pytest.approx(5.377)
 assert CnbcProvider({}).fetch_history('GB10Y',date(2026,9,1),date(2026,9,30))==[]
 with pytest.raises(ValueError): CnbcProvider({}).validate_symbol('')
def test_catalog_napoleon_and_nasdaq():
 import yaml
 catalog=yaml.safe_load((Path(__file__).resolve().parents[1]/'catalog.yaml').read_text())
 by_id={v['id']:v for v in catalog['variables']}
 assert by_id['napoleon']['provider']=='bdor' and by_id['napoleon']['symbol']=='20-francs-napoleon-or' and by_id['napoleon']['unit']=='EUR'
 assert by_id['nasdaq']['provider']=='yahoo' and by_id['nasdaq']['symbol']=='^IXIC' and by_id['nasdaq']['unit']=='USD'
 assert 'gold' not in by_id
 topics={t['id'] for t in catalog['news_topics']}
 assert {'napoleon_or','nasdaq_stocks'} <= topics
 for vid in ('napoleon','nasdaq'):
  for t in by_id[vid]['news_topics']: assert t in topics
 for vid in ('oat_10y','us_10y','uk_10y','de_10y','brent','wti','napoleon','nasdaq','bitcoin','spacex','eurusd'):
  assert by_id[vid].get('icon'), vid
def test_bdor_parses_fixing(monkeypatch):
 from plugins.bdor.plugin import BdorProvider
 import plugins.bdor.plugin as bdor_mod
 from plugins.base.plugin import ProviderError
 html=('Actualisation en direct - 02/10/2026 ... '
  '<a href=\"/produits/20-francs-napoleon-or\">20 Francs Napoléon Or</a> ... '
  '<span class=\"prixAffiche\"> 716,90 € </span>')
 monkeypatch.setattr(bdor_mod,'get',lambda *a,**k: html)
 obs=BdorProvider({}).fetch_latest('20-francs-napoleon-or')
 assert obs.value==pytest.approx(716.9) and obs.source=='bdor' and str(obs.date)=='2026-10-02'
 assert BdorProvider({}).fetch_history('20-francs-napoleon-or',date(2026,10,1),date(2026,10,3))[0].value==pytest.approx(716.9)
 with pytest.raises(ProviderError): BdorProvider({}).fetch_latest('no-such-product')
 monkeypatch.setattr(bdor_mod,'get',lambda *a,**k: '<html><body>bot check</body></html>')
 with pytest.raises(ProviderError,match='unexpected format'): BdorProvider({}).fetch_latest('20-francs-napoleon-or')
 with pytest.raises(ValueError): BdorProvider({}).validate_symbol('has space')
def test_yahoo_quotes_index_symbols(monkeypatch):
 from plugins.yahoo.plugin import YahooProvider
 import plugins.yahoo.plugin as yahoo_mod
 seen={}
 def fake_get(url,*a,**k):
  seen['url']=url
  return '{\"chart\":{\"result\":[{\"meta\":{\"regularMarketPrice\":27190.86,\"regularMarketTime\":1790947800}}],\"error\":null}}'
 monkeypatch.setattr(yahoo_mod,'get',fake_get)
 obs=YahooProvider({}).fetch_latest('^IXIC')
 assert obs.value==pytest.approx(27190.86) and '%5EIXIC' in seen['url']
def test_variable_icon_config_and_result(tmp_path):
 from core.config import load_config
 from core.models import Variable as Var
 from core.services import latest
 path=tmp_path/'watcher.yaml'
 path.write_text('version: 1\nvariables: [{id: x, label: X, provider: test, symbol: s, unit: USD, icon: "🚀"}]\nnews_topics: []\nfeeds: []\n')
 variables,_,_=load_config({'test':Provider()},path)
 assert variables[0].icon=='🚀'
 path.write_text('version: 1\nvariables: [{id: x, label: X, provider: test, symbol: s, unit: USD}]\nnews_topics: []\nfeeds: []\n')
 assert load_config({'test':Provider()},path)[0][0].icon==''
 db=connection(tmp_path/'icon.sqlite3')
 upsert(db,Observation('eurusd',date(2026,10,2),1.10,'USD/EUR','yahoo',datetime.now(timezone.utc)))
 res=latest([Var('x','X','test','s','USD',30,(),'🚀')],{'test':_live_provider(1.0,date(2026,10,2))},db)
 assert res[0].icon=='🚀' and res[0].secondary_unit=='EUR'
