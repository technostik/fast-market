from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
@dataclass(frozen=True, slots=True)
class Variable:
 id: str; label: str; provider: str; symbol: str; unit: str; max_age_days: int; news_topics: tuple[str,...]
@dataclass(frozen=True, slots=True)
class Topic:
 id: str; label: str; query: str; lang: str
@dataclass(frozen=True, slots=True)
class NewsItem:
 topic: str; title: str; source: str; published_at: datetime | None; url: str
@dataclass(frozen=True, slots=True)
class VariableResult:
 id: str; label: str; value: float|None; unit: str; as_of: date|None; source: str|None; change_abs: float|None; change_pct: float|None; stale: bool; error: str|None
