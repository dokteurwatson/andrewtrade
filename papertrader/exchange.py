from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import ccxt


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class ExchangeClient:
    def __init__(self, exchange_id: str) -> None:
        exchange_cls = getattr(ccxt, exchange_id)
        self._client = exchange_cls({"enableRateLimit": True, "timeout": 30000})
        self._markets_loaded = False

    def _ensure_markets(self) -> None:
        if not self._markets_loaded:
            self._client.load_markets()
            self._markets_loaded = True

    def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> List[Candle]:
        self._ensure_markets()
        ohlcv = self._client.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
        return [
            Candle(
                timestamp=int(entry[0]),
                open=float(entry[1]),
                high=float(entry[2]),
                low=float(entry[3]),
                close=float(entry[4]),
                volume=float(entry[5]),
            )
            for entry in ohlcv
        ]

    def fetch_last_prices(self, symbols: List[str]) -> Dict[str, float]:
        self._ensure_markets()
        tickers = self._client.fetch_tickers(symbols)
        return {symbol: float(ticker["last"]) for symbol, ticker in tickers.items() if ticker.get("last") is not None}
