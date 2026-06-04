"""
Paper trading client — zelfde interface als IBKRClient maar zonder IBKR.

Data: yfinance (1m bars, ~15min vertraging) of Polygon.io (real-time, free tier).
Orders: intern gesimuleerd, cash gepersisteerd via StateStore.

Gebruik:
  PAPER_MODE=true          → deze client
  DATA_SOURCE=yfinance     → Yahoo Finance (gratis, 15min vertraging)
  DATA_SOURCE=polygon      → Polygon.io (real-time, gratis tier 15 req/min)
  POLYGON_API_KEY=...      → verplicht bij DATA_SOURCE=polygon
  PAPER_CAPITAL=1000       → startkapitaal (alleen bij eerste run)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

import yfinance as yf

from .market_data import fetch_1m
from .state import trading_date

if TYPE_CHECKING:
    from .state import DayState, StateStore


class PaperClient:
    def __init__(
        self,
        start_capital: float,
        data_source: str = "yfinance",
        polygon_api_key: str = "",
    ) -> None:
        self._start_capital = start_capital
        self._cash          = start_capital
        self._data_source   = data_source.lower()
        self._polygon_key   = polygon_api_key

        # StateStore koppeling voor cash persistentie
        self._store: Optional["StateStore"] = None
        self._state: Optional["DayState"]   = None

        self._positions: Dict[str, int] = {}
        self._callbacks: Dict[str, Callable[[str, float, float, float, float, float], None]] = {}
        self._running    = False
        self._poll_thread: Optional[threading.Thread] = None
        self._last_bar:  Dict[str, str] = {}

        logging.info(
            "PaperClient gestart | kapitaal=$%.2f | data=%s",
            start_capital, self._data_source,
        )

    def bind_state(self, store: "StateStore", state: "DayState") -> None:
        """Koppel StateStore zodat cash gepersisteerd wordt. Laad cash uit state."""
        self._store = store
        self._state = state
        if state.cash > 0:
            self._cash = state.cash
            logging.info("PaperClient: cash geladen uit state: $%.2f", self._cash)
        else:
            # Eerste run — sla startkapitaal op
            self._cash = self._start_capital
            self._persist_cash()

    def _persist_cash(self) -> None:
        if self._store and self._state:
            self._store.update_cash(self._state, self._cash)

    # ------------------------------------------------------------------
    # Verbinding
    # ------------------------------------------------------------------

    def connect(self) -> None:
        logging.info("PaperClient: geen verbinding nodig (paper mode).")

    def disconnect(self) -> None:
        self.stop_stream()
        logging.info("PaperClient: losgekoppeld.")

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_cash(self) -> float:
        return self._cash

    def get_buying_power(self) -> float:
        return self._cash

    # ------------------------------------------------------------------
    # OTC filter
    # ------------------------------------------------------------------

    def is_tradable(self, ticker: str) -> bool:
        try:
            info = yf.Ticker(ticker).fast_info
            price = info.last_price
            if price and price > 0:
                return True
            logging.info("Paper OTC-filter: %s geen data → overgeslagen.", ticker)
            return False
        except Exception as exc:
            logging.warning("Paper is_tradable check mislukt voor %s: %s", ticker, exc)
            return False

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def buy_market(self, ticker: str, shares: int) -> str:
        price = self.get_latest_price(ticker)
        if price is None:
            raise RuntimeError(f"Geen prijs beschikbaar voor {ticker}")

        cost = price * shares
        if cost > self._cash:
            raise RuntimeError(
                f"Onvoldoende cash: nodig=${cost:.2f} beschikbaar=${self._cash:.2f}"
            )

        self._cash -= cost
        self._positions[ticker] = self._positions.get(ticker, 0) + shares
        self._persist_cash()

        order_id = f"paper-buy-{ticker}-{int(time.time())}"
        logging.info("PAPER BUY %s x%d @ $%.4f | cash=$%.2f", ticker, shares, price, self._cash)
        return order_id

    def sell_market(self, ticker: str, shares: int) -> str:
        price = self.get_latest_price(ticker)
        if price is None:
            raise RuntimeError(f"Geen prijs beschikbaar voor {ticker}")

        held = self._positions.get(ticker, 0)
        if shares > held:
            shares = held
        if shares == 0:
            raise RuntimeError(f"Geen positie in {ticker}")

        proceeds = price * shares
        self._cash += proceeds
        self._positions[ticker] = held - shares
        if self._positions[ticker] == 0:
            del self._positions[ticker]
        self._persist_cash()

        order_id = f"paper-sell-{ticker}-{int(time.time())}"
        logging.info("PAPER SELL %s x%d @ $%.4f | cash=$%.2f", ticker, shares, price, self._cash)
        return order_id

    def close_all_positions(self) -> None:
        for ticker, shares in list(self._positions.items()):
            if shares > 0:
                try:
                    self.sell_market(ticker, shares)
                except Exception as exc:
                    logging.error("EOD close mislukt voor %s: %s", ticker, exc)
        logging.info(
            "PAPER EOD: alle posities gesloten | cash=$%.2f (start=$%.2f pnl=%+.2f)",
            self._cash, self._start_capital, self._cash - self._start_capital,
        )

    # ------------------------------------------------------------------
    # Prijzen ophalen
    # ------------------------------------------------------------------

    def get_latest_price(self, ticker: str) -> Optional[float]:
        if self._data_source == "polygon":
            return self._polygon_last_price(ticker)
        return self._yfinance_last_price(ticker)

    def _yfinance_last_price(self, ticker: str) -> Optional[float]:
        try:
            data = yf.download(ticker, period="1d", interval="1m", progress=False, auto_adjust=True)
            if data.empty:
                return None
            if isinstance(data.columns, __import__("pandas").MultiIndex):
                data.columns = data.columns.get_level_values(0)
            return float(data["Close"].iloc[-1])
        except Exception as exc:
            logging.warning("yfinance prijs mislukt voor %s: %s", ticker, exc)
            return None

    def _polygon_last_price(self, ticker: str) -> Optional[float]:
        try:
            import urllib.request, json
            url = (
                f"https://api.polygon.io/v2/last/trade/{ticker}"
                f"?apiKey={self._polygon_key}"
            )
            with urllib.request.urlopen(url, timeout=5) as r:
                data = json.loads(r.read())
            return float(data["results"]["p"])
        except Exception as exc:
            logging.warning("Polygon prijs mislukt voor %s: %s", ticker, exc)
            return None

    # ------------------------------------------------------------------
    # Real-time bars (polling elke 60s)
    # ------------------------------------------------------------------

    def subscribe_bars(
        self,
        tickers: List[str],
        on_bar: Callable[[str, float, float, float, float, float], None],
    ) -> None:
        for ticker in tickers:
            self._callbacks[ticker] = on_bar

    def start_stream(self) -> None:
        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        logging.info("PaperClient poll loop gestart (interval=60s).")

    def stop_stream(self) -> None:
        self._running = False

    def _poll_loop(self) -> None:
        while self._running:
            for ticker, callback in list(self._callbacks.items()):
                try:
                    self._emit_last_bar(ticker, callback)
                except Exception as exc:
                    logging.warning("Poll fout voor %s: %s", ticker, exc)
            time.sleep(60)

    def _emit_last_bar(self, ticker: str, callback) -> None:
        if self._data_source == "polygon":
            self._emit_polygon_bar(ticker, callback)
        else:
            self._emit_yfinance_bar(ticker, callback)

    def _emit_yfinance_bar(self, ticker: str, callback) -> None:
        data = fetch_1m(ticker, trading_date())
        if data is None or len(data) < 2:
            return
        bar = data.iloc[-2]
        ts  = str(data.index[-2])
        if self._last_bar.get(ticker) == ts:
            return
        self._last_bar[ticker] = ts
        callback(ticker, float(bar["Open"]), float(bar["High"]), float(bar["Low"]), float(bar["Close"]), float(bar["Volume"]))

    def _emit_polygon_bar(self, ticker: str, callback) -> None:
        try:
            import urllib.request, json
            from datetime import date
            today = date.today().isoformat()
            url = (
                f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/{today}/{today}"
                f"?adjusted=true&sort=desc&limit=2&apiKey={self._polygon_key}"
            )
            with urllib.request.urlopen(url, timeout=5) as r:
                data = json.loads(r.read())
            results = data.get("results", [])
            if len(results) < 2:
                return
            bar = results[1]
            ts  = str(bar["t"])
            if self._last_bar.get(ticker) == ts:
                return
            self._last_bar[ticker] = ts
            callback(ticker, float(bar["o"]), float(bar["h"]), float(bar["l"]), float(bar["c"]), float(bar["v"]))
        except Exception as exc:
            logging.warning("Polygon bar mislukt voor %s: %s", ticker, exc)
