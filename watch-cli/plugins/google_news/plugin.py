from __future__ import annotations
import email.utils
from datetime import datetime,timezone
from xml.etree import ElementTree as ET
from core.http import get
from core.models import NewsItem
class GoogleNewsProvider:
 def __init__(self,config): pass
 def fetch(self,topic):
  xml=get('https://news.google.com/rss/search',params={'q':topic.query,'hl':f'{topic.lang}-US','gl':'US','ceid':f'US:{topic.lang}'})
  root=ET.fromstring(xml); items=[]
  for node in root.findall('.//item'):
   raw=node.findtext('pubDate'); published=email.utils.parsedate_to_datetime(raw).astimezone(timezone.utc) if raw else None
   source=node.findtext('source') or 'Google News'; items.append(NewsItem(topic.id,node.findtext('title') or '',source,published,node.findtext('link') or ''))
  return items
