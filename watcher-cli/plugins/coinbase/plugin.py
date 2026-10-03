from __future__ import annotations
import json
from datetime import date, datetime, timezone
from core.http import get
from plugins.base.plugin import Observation, ProviderDescriptor, ProviderError

# Coin id (coingecko-style, e.g. bitcoin) -> Coinbase base currency.
_COIN_MAP = {
    'bitcoin': 'BTC',
    'ethereum': 'ETH',
    'solana': 'SOL',
    'dogecoin': 'DOGE',
    'cardano': 'ADA',
    'litecoin': 'LTC',
}

def _base_currency(coin: str) -> str:
    if not coin:
        raise ValueError('symbol must be coin:currency, for example bitcoin:eur')
    return _COIN_MAP.get(coin.lower(), coin.upper())


def _split(symbol: str) -> tuple[str, str]:
    if symbol.count(':') != 1 or not all(symbol.split(':')):
        raise ValueError('symbol must be coin:currency, for example bitcoin:eur')
    coin, currency = symbol.split(':')
    return _base_currency(coin), currency.upper()


def _spot_latest(symbol: str) -> Observation:
    base, currency = _split(symbol)
    data = json.loads(get(f'https://api.coinbase.com/v2/prices/{base}-{currency}/spot'))
    try:
        amount = data['data']['amount']
    except (KeyError, TypeError):
        raise ProviderError(f'Coinbase did not return {symbol}: {str(data)[:200]!r}')
    try:
        value = float(amount)
    except (TypeError, ValueError) as exc:
        raise ProviderError(f'Coinbase returned invalid price for {symbol!r}: {amount!r}') from exc
    return Observation('', date.today(), value, '', 'coinbase', datetime.now(timezone.utc))


def _exchange_history(symbol: str, start: date, end: date) -> list[Observation]:
    base, currency = _split(symbol)
    data = json.loads(get(
        f'https://api.exchange.coinbase.com/products/{base}-{currency}/candles',
        params={'granularity': '86400'},
    ))
    if not isinstance(data, list):
        raise ProviderError(f'Coinbase did not return history for {symbol}: {str(data)[:200]!r}')
    out = []
    for row in data:
        try:
            ts, _low, _high, _open, close, _vol = row
            d = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
        except (TypeError, ValueError, IndexError):
            continue
        if start <= d <= end:
            out.append(Observation('', d, float(close), '', 'coinbase', datetime.now(timezone.utc)))
    out.sort(key=lambda o: o.date)
    return out


class CoinbaseProvider:
    descriptor = ProviderDescriptor('coinbase', (), True, 'coin:currency, for example bitcoin:eur')
    def __init__(self, config): pass
    def validate_symbol(self, s):
        _split(s)
    def fetch_latest(self, s):
        return _spot_latest(s)
    def fetch_history(self, s, start, end):
        return _exchange_history(s, start, end)
