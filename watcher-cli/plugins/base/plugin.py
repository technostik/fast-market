from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
class ProviderError(Exception): pass
class RateLimitError(ProviderError): pass
class MissingCredentialsError(ProviderError):
    def __init__(self, env_var: str): self.env_var=env_var; super().__init__(f"Missing credentials: set {env_var} in the watcher .env file.")
class HistoryNotSupported(ProviderError): pass
@dataclass(frozen=True, slots=True)
class Observation:
    variable_id: str
    date: date
    value: float
    unit: str
    source: str
    fetched_at: datetime
@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    id: str
    required_env: tuple[str, ...] = ()
    supports_history: bool = True
    symbol_help: str = ""
@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    provider_class: type
    descriptor: ProviderDescriptor
class Provider(Protocol):
    descriptor: ProviderDescriptor
    def validate_symbol(self, symbol: str) -> None: ...
    def fetch_latest(self, symbol: str) -> Observation: ...
    def fetch_history(self, symbol: str, start: date, end: date) -> list[Observation]: ...
