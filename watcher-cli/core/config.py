from __future__ import annotations
import os, re
from pathlib import Path
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from common.core.paths import get_tool_config_path
from core.models import Topic, Variable
_DURATION=re.compile(r"^(\d+)([dhmy])$")
def duration_days(value: str)->int:
 m=_DURATION.fullmatch(value)
 if not m: raise ValueError("max_age must be a duration such as 1d, 24h, 6m, or 1y")
 return int(m.group(1))*{'h':1,'d':1,'m':30,'y':365}[m.group(2)]
class VariableFile(BaseModel):
 model_config=ConfigDict(extra='forbid')
 id:str; label:str; provider:str; symbol:str; unit:str; max_age:str='1d'; news_topics:list[str]=Field(default_factory=list); icon:str=''
 @field_validator('id')
 @classmethod
 def identifier(cls,v):
  if not re.fullmatch(r'[a-z][a-z0-9_]*',v): raise ValueError('id must be lowercase letters, numbers, and underscores')
  return v
class TopicFile(BaseModel):
 model_config=ConfigDict(extra='forbid')
 id:str; label:str; query:str; lang:str='en'
 @field_validator('lang')
 @classmethod
 def language(cls,v):
  if v not in {'en','fr'}: raise ValueError('lang must be en or fr')
  return v
class FeedFile(BaseModel):
 model_config=ConfigDict(extra='forbid')
 topic:str; url:str
class WatchFile(BaseModel):
 model_config=ConfigDict(extra='forbid')
 version:int=1; variables:list[VariableFile]=Field(default_factory=list); news_topics:list[TopicFile]=Field(default_factory=list); feeds:list[FeedFile]=Field(default_factory=list)
 @model_validator(mode='after')
 def references(self):
  topics={t.id for t in self.news_topics}
  missing={x for v in self.variables for x in v.news_topics if x not in topics}|{f.topic for f in self.feeds if f.topic not in topics}
  if missing: raise ValueError('unknown news topic reference(s): '+', '.join(sorted(missing)))
  if len({v.id for v in self.variables}) != len(self.variables): raise ValueError('variable ids must be unique')
  return self
def config_path()->Path: return get_tool_config_path('watcher').with_name('watcher.yaml')
def env_path()->Path: return config_path().with_name('.env')
def load_env()->None:
 p=env_path()
 if p.exists():
  for line in p.read_text().splitlines():
   if '=' in line and not line.lstrip().startswith('#'):
    key,value=line.split('=',1); os.environ.setdefault(key.strip(),value.strip())
def default_text()->str:
 catalog=Path(__file__).resolve().parents[1]/'catalog.yaml'
 data=yaml.safe_load(catalog.read_text()); return '# Add catalog variables with `watcher wizard`, or edit this file.\n'+yaml.safe_dump({'version': 1, 'variables': [], 'news_topics': data['news_topics'], 'feeds': []}, sort_keys=False)
def load_config(registry: dict, path:Path|None=None)->tuple[list[Variable],list[Topic],list[FeedFile]]:
 p=path or config_path()
 if not p.exists(): raise ValueError(f'Configuration does not exist: {p}. Run watcher setup or watcher wizard.')
 try: raw=yaml.safe_load(p.read_text()) or {}; parsed=WatchFile.model_validate(raw)
 except (yaml.YAMLError,ValidationError) as exc:
  line = getattr(getattr(exc, 'problem_mark', None), 'line', None)
  location = f' at line {line + 1}' if line is not None else ''
  raise ValueError(f'Invalid {p}{location}: {exc}') from exc
 for v in parsed.variables:
  if v.provider not in registry: raise ValueError(f"Variable '{v.id}' uses unknown provider '{v.provider}'.")
  try: registry[v.provider].validate_symbol(v.symbol)
  except Exception as exc: raise ValueError(f"Variable '{v.id}' has invalid {v.provider} symbol '{v.symbol}': {exc}") from exc
 return ([Variable(v.id,v.label,v.provider,v.symbol,v.unit,duration_days(v.max_age),tuple(v.news_topics),v.icon) for v in parsed.variables], [Topic(t.id,t.label,t.query,t.lang) for t in parsed.news_topics], parsed.feeds)
def write_config(data:dict,path:Path|None=None)->None:
 p=path or config_path(); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(yaml.safe_dump(data,sort_keys=False))
