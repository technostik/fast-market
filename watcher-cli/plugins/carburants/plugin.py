from __future__ import annotations
import json
from datetime import date, datetime, timezone

from core.http import get
from plugins.base.plugin import Observation, ProviderDescriptor, ProviderError

_BASE_URL = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/records"

_FUEL_ALIASES = {
    "gazole": "gazole",
    "gasoil": "gazole",
    "diesel": "gazole",
    "sp95": "sp95",
    "sp98": "sp98",
    "e10": "e10",
    "e85": "e85",
    "gplc": "gplc",
    "gpl": "gplc",
}


def _split(symbol: str) -> tuple[str, str]:
    parts = symbol.split(":")
    if len(parts) == 1:
        locator, fuel = symbol, "gazole"
    elif len(parts) == 2 and all(parts):
        locator, fuel = parts
    else:
        raise ValueError("symbol must be a station id or 'station:fuel', for example 9190002 or 9190002:gazole")
    fuel = _FUEL_ALIASES.get(fuel.strip().lower())
    if fuel is None:
        raise ValueError("unknown fuel; use one of: gazole, sp95, sp98, e10, e85, gplc")
    locator = locator.strip()
    if not locator:
        raise ValueError("station locator must not be empty")
    return locator, fuel


def _fetch_records(locator: str) -> list[dict]:
    params = {"limit": 100}
    if locator.isdigit():
        params["where"] = f"id={locator}"
    else:
        params["q"] = locator
    text = get(_BASE_URL, params=params)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProviderError(f"Carburants returned invalid JSON: {text[:200]!r}") from exc
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("results"), list):
            return data["results"]
        if isinstance(data.get("records"), list):
            return data["records"]
        # single record
        if "id" in data or "gazole_prix" in data:
            return [data]
    raise ProviderError(f"Carburants returned unexpected format: {text[:200]!r}")


def _match_station(records: list[dict], locator: str) -> dict:
    if locator.isdigit():
        for r in records:
            if str(r.get("id")) == locator:
                return r
    if records:
        return records[0]
    raise ProviderError("Carburants returned no station for " + repr(locator))


def _parse_date(value) -> date:
    if value is None:
        return date.today()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).date()
        except (ValueError, OSError, OverflowError):
            return date.today()
    text = str(value).strip()
    if not text:
        return date.today()
    # ISO datetime or date
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return date.today()


def _fetch(symbol: str) -> Observation:
    locator, fuel = _split(symbol)
    records = _fetch_records(locator)
    station = _match_station(records, locator)
    field = f"{fuel}_prix"
    if field not in station or station.get(field) is None:
        raise ProviderError(f"Carburants station has no price for {fuel}")
    try:
        value = float(station[field])
    except (TypeError, ValueError) as exc:
        raise ProviderError(f"Carburants returned invalid price for {fuel}: {station.get(field)!r}") from exc
    maj_field = f"{fuel}_maj"
    d = _parse_date(station.get(maj_field))
    return Observation("", d, value, "", "carburants", datetime.now(timezone.utc))


class CarburantsProvider:
    descriptor = ProviderDescriptor("carburants", (), True, "station id or 'station:fuel', for example 9190002 or 9190002:gazole (fuel: gazole, sp95, sp98, e10, e85, gplc)")
    def __init__(self, config):
        pass
    def validate_symbol(self, symbol):
        _split(symbol)
    def fetch_latest(self, symbol):
        return _fetch(symbol)
    def fetch_history(self, symbol, start, end):
        try:
            o = _fetch(symbol)
        except Exception:
            return []
        if start <= o.date <= end:
            return [o]
        return []


# alias for tests that may use other class names
FuelProvider = CarburantsProvider
FuelStationProvider = CarburantsProvider
StationProvider = CarburantsProvider
PrixCarburantsProvider = CarburantsProvider
OpenDataProvider = CarburantsProvider
