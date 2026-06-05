"""
Bar-stream providers — yfinance, Polygon of Alpaca WebSocket.

Factory:
    build_bar_stream(settings) → YfinanceBarStream | PolygonBarStream | AlpacaBarStream
"""
from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from .market_data import fetch_1m
from .state import trading_date

if TYPE_CHECKING:
    from .config import Settings

BarHandler = Callable[..., None]


def _call_bar(
    handler: BarHandler,
    ticker: str,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    *,
    is_new_bar: bool = True,
) -> None:
    try:
        handler(ticker, open_, high, low, close, volume, is_new_bar)
    except TypeError:
        handler(ticker, open_, high, low, close, volume)


class YfinanceBarStream:
    """Poll yfinance 1m bars (typisch ~15 min vertraging)."""

    def __init__(self, poll_seconds: int = 60) -> None:
        self._poll_seconds = max(15, poll_seconds)
        self._callbacks: Dict[str, BarHandler] = {}
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._last_bar_ts: Dict[str, str] = {}

    def subscribe_bars(self, tickers: List[str], on_bar: BarHandler) -> None:
        for ticker in tickers:
            self._callbacks[ticker] = on_bar

    def start_stream(self) -> None:
        if self._running:
            return
        self._running = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="yfinance-bars",
        )
        self._poll_thread.start()
        logging.info(
            "Yfinance bar-stream gestart (poll=%ds, ~15min marktdata-delay)",
            self._poll_seconds,
        )

    def stop_stream(self) -> None:
        self._running = False
        logging.info("Yfinance bar-stream gestopt.")

    def _poll_loop(self) -> None:
        while self._running:
            for ticker, handler in list(self._callbacks.items()):
                try:
                    self._emit_bar(ticker, handler)
                except Exception as exc:
                    logging.warning("Yfinance bar poll %s: %s", ticker, exc)
            time.sleep(self._poll_seconds)

    def _emit_bar(self, ticker: str, handler: BarHandler) -> None:
        data = fetch_1m(ticker, trading_date())
        if data is None or len(data) < 2:
            return
        bar = data.iloc[-2]
        ts = str(data.index[-2])
        if self._last_bar_ts.get(ticker) == ts:
            return
        self._last_bar_ts[ticker] = ts
        _call_bar(
            handler,
            ticker,
            float(bar["Open"]),
            float(bar["High"]),
            float(bar["Low"]),
            float(bar["Close"]),
            float(bar["Volume"]),
            is_new_bar=True,
        )


class PolygonBarStream:
    """Poll Polygon 1m aggregates (vereist API key)."""

    def __init__(self, api_key: str, poll_seconds: int = 60) -> None:
        self._api_key = api_key
        self._poll_seconds = max(15, poll_seconds)
        self._callbacks: Dict[str, BarHandler] = {}
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._last_bar_ts: Dict[str, str] = {}

    def subscribe_bars(self, tickers: List[str], on_bar: BarHandler) -> None:
        for ticker in tickers:
            self._callbacks[ticker] = on_bar

    def start_stream(self) -> None:
        if not self._api_key:
            raise RuntimeError("POLYGON_API_KEY vereist voor DATA_SOURCE=polygon")
        if self._running:
            return
        self._running = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="polygon-bars",
        )
        self._poll_thread.start()
        logging.info("Polygon bar-stream gestart (poll=%ds)", self._poll_seconds)

    def stop_stream(self) -> None:
        self._running = False
        logging.info("Polygon bar-stream gestopt.")

    def _poll_loop(self) -> None:
        while self._running:
            for ticker, handler in list(self._callbacks.items()):
                try:
                    self._emit_bar(ticker, handler)
                except Exception as exc:
                    logging.warning("Polygon bar poll %s: %s", ticker, exc)
            time.sleep(self._poll_seconds)

    def _emit_bar(self, ticker: str, handler: BarHandler) -> None:
        import json
        import urllib.request

        today = trading_date().isoformat()
        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/"
            f"{today}/{today}?adjusted=true&sort=desc&limit=2&apiKey={self._api_key}"
        )
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        results = data.get("results", [])
        if len(results) < 2:
            return
        bar = results[1]
        ts = str(bar["t"])
        if self._last_bar_ts.get(ticker) == ts:
            return
        self._last_bar_ts[ticker] = ts
        _call_bar(
            handler,
            ticker,
            float(bar["o"]),
            float(bar["h"]),
            float(bar["l"]),
            float(bar["c"]),
            float(bar["v"]),
            is_new_bar=True,
        )


def build_bar_stream(settings: "Settings"):
    """
    Factory: maak de juiste bar-stream op basis van DATA_SOURCE.

    Returns één van:
        FinazonBarStream  (DATA_SOURCE=finazon)  — SIP real-time, $19/mnd non-pro
        AlpacaBarStream   (DATA_SOURCE=alpaca)   — IEX real-time, gratis paper
        PolygonBarStream  (DATA_SOURCE=polygon)  — SIP/IEX, betaald
        YfinanceBarStream (DATA_SOURCE=yfinance) — ~15 min vertraging, gratis
    """
    src = settings.effective_data_source()

    if src == "finazon":
        from .finazon_stream import FinazonBarStream
        return FinazonBarStream(api_key=settings.finazon_api_key)

    if src == "alpaca":
        from .alpaca_stream import AlpacaBarStream
        return AlpacaBarStream(
            api_key=settings.alpaca_api_key,
            api_secret=settings.alpaca_api_secret,
            feed=settings.alpaca_data_feed,
        )

    if src == "polygon":
        return PolygonBarStream(
            api_key=settings.polygon_api_key,
            poll_seconds=settings.bar_poll_seconds,
        )

    return YfinanceBarStream(poll_seconds=settings.bar_poll_seconds)
