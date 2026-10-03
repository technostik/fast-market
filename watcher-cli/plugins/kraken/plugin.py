from __future__ import annotations
import json
from datetime import date, datetime, timezone
from core.http import get
from plugins.base.plugin import Observation, ProviderDescriptor, ProviderError

# Coin id (coingecko-style, e.g. bitcoin) -> Kraken base asset.
# Kraken uses XBT for Bitcoin; most others are plain uppercase symbols.
_COIN_MAP = {
    'bitcoin': 'XBT',
    'ethereum': 'ETH',
    'solana': 'SOL',
    'dogecoin': 'DOGE',
    'cardano': 'ADA',
    'litecoin': 'LTC',
}

def _split(symbol: str) -> tuple[str, str]:
    if symbol.count(':') != 1 or not all(symbol.split(':')):
        raise ValueError('symbol must be coin:currency, for example bitcoin:eur')
    coin, currency = symbol.split(':')
    base = _COIN_MAP.get(coin.lower(), coin.upper())
    return base, currency.upper()


def _kraken_latest(symbol: str) -> Observation:
    base, currency = _split(symbol)
    pair = f'{base}{currency}'
    data = json.loads(get('https://api.kraken.com/0/public/Ticker', params={'pair': pair}))
    if data.get('error'):
        raise ProviderError(f'Kraken error for {symbol}: {data["error"]}')
    result = data.get('result') or {}
    # Result key varies (e.g. XXBTZUSD vs XBTUSD); take the first non-'last' entry.
    entries = [(k, v) for k, v in result.items() if k != 'last']
    if not entries:
        raise ProviderError(f'Kraken did not return {symbol}')
    ticker = entries[0][1]
    try:
        value = float(ticker['c'][0])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ProviderError(f'Kraken returned unexpected ticker for {symbol!r}') from exc
    return Observation('', date.today(), value, '', 'kraken', datetime.now(timezone.utc))


def _kraken_history(symbol: str, start: date, end: date) -> list[Observation]:
    base, currency = _split(symbol)
    pair = f'{base}{currency}'
    data = json.loads(get('https://api.kraken.com/0/public/OHLC', params={'pair': pair, 'interval': '1440'}))
    if data.get('error'):
        raise ProviderError(f'Kraken error for {symbol}: {data["error"]}')
    result = data.get('result') or {}
    entries = [(k, v) for k, v in result.items() if k != 'last']
    if not entries:
        raise ProviderError(f'Kraken did not return history for {symbol}')
    candles = entries[0][1]
    out = []
    for row in candles:
        try:
            ts, _o, _h, _l, close = row[0], row[1], row[2], row[3], row[4]
            d = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
        except (TypeError, ValueError, IndexError):
            continue
        if start <= d <= end:
            out.append(Observation('', d, float(close), '', 'kraken', datetime.now(timezone.utc)))
    out.sort(key=lambda o: o.date)
    return out


class KrakenProvider:
    """Primary Kraken source with Coinbase-spot fallback on failure/rate limit.

    Source field reflects the actual source used ('kraken' or 'coinbase'),
    so staleness and provenance stay honest.
    """
    descriptor = ProviderDescriptor('kraken', (), True, 'coin:currency, for example bitcoin:eur')
    def __init__(self, config): pass
    def validate_symbol(self, s):
        _split(s)
    def fetch_latest(self, s):
        try:
            return _kraken_latest(s)
        except Exception:
            from plugins.coinbase.plugin import CoinbaseProvider
            return CoinbaseProvider({}).fetch_latest(s)
    def fetch_history(self, s, start, end):
        try:
            out = _kraken_history(s, start, end)
            if out:
                return out
        except Exception:
            pass
        from plugins.coinbase.plugin import CoinbaseProvider
        return CoinbaseProvider({}).fetch_history(s, start, end)
