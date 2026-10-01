from __future__ import annotations
import time
from typing import Any
import httpx
from common import structlog
from plugins.base.plugin import ProviderError, RateLimitError
logger=structlog.get_logger(__name__)
def get(url:str, *, params:dict[str,Any]|None=None)->str:
 start=time.monotonic()
 try:
  response=httpx.get(url,params=params,timeout=20,follow_redirects=True,headers={'User-Agent':'fast-market-watch/0.1'})
  if response.status_code==429: raise RateLimitError('Provider rate limit reached')
  response.raise_for_status(); logger.info('provider_http',status=response.status_code,latency_ms=round((time.monotonic()-start)*1000)); return response.text
 except RateLimitError: raise
 except httpx.HTTPError as exc: raise ProviderError(f'HTTP request failed: {exc}') from exc
