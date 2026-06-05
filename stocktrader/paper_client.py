"""
PaperClient — gesimuleerde orders (paper broker).

Verantwoordelijk voor: cash-beheer, gesimuleerde buy/sell, is_tradable.
Bar-stream wordt extern aangemaakt door Trader en via subscribe_bars geïnjecteerd.

DATA_SOURCE is niet meer van toepassing hier; de bar-stream leeft in bar_stream.py.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

import yfinance as yf

if TYPE_CHECKING:
    from .state import DayState, StateStore


class PaperClient:
    def __init__(
        self,
        start_capital: float,
        poll_seconds: int = 60,
    ) -> None:
        self._start_capital = start_capital
        self._cash = start_capital
        self._positions: Dict[str, int] = {}
        self._price_cache: Dict[str, float] = {}

        # Intern bar-stream object geïnjecteerd via subscribe_bars / start_stream
        self._bar_stream = None

        logging.info(
            "PaperClient gestart | kapitaal=$%.2f",
            start_capital,
        )

        # StateStore koppeling voor cash persistentie
        self._store: Optional["StateStore"] = None
        self._state: Optional["DayState"] = None

    def bind_state(self, store: "StateStore", state: "DayState") -> None:
        self._store = store
        self._state = state
        # cash >= 0 is geldig (ook €0 na verlies); alleen negatief = niet ingesteld
        if state.cash >= 0:
            self._cash = state.cash
            logging.info("PaperClient: cash geladen uit state: $%.2f", self._cash)
        else:
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
        logging.info("PaperClient: losgekoppeld.")

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_cash(self) -> float:
        return self._cash

    def get_buying_power(self) -> float:
        return self._cash

    # ------------------------------------------------------------------
    # Prijzen
    # ------------------------------------------------------------------

    def update_last_price(self, ticker: str, price: float) -> None:
        self._price_cache[ticker] = price

    def get_latest_price(self, ticker: str) -> Optional[float]:
        cached = self._price_cache.get(ticker)
        if cached is not None and cached > 0:
            return cached
        return self._yfinance_last_price(ticker)

    def _yfinance_last_price(self, ticker: str) -> Optional[float]:
        try:
            data = yf.download(
                ticker, period="1d", interval="1m", progress=False, auto_adjust=True
            )
            if data.empty:
                return None
            if isinstance(data.columns, __import__("pandas").MultiIndex):
                data.columns = data.columns.get_level_values(0)
            return float(data["Close"].iloc[-1])
        except Exception as exc:
            logging.warning("yfinance prijs mislukt voor %s: %s", ticker, exc)
            return None

    # ------------------------------------------------------------------
    # OTC filter
    # ------------------------------------------------------------------

    def is_tradable(self, ticker: str) -> bool:
        # Als we een verse prijs in cache hebben, is het ticker al bewezen bruikbaar
        if ticker in self._price_cache:
            return True
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
        logging.info(
            "PAPER BUY %s x%d @ $%.4f | cash=$%.2f",
            ticker, shares, price, self._cash,
        )
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
        logging.info(
            "PAPER SELL %s x%d @ $%.4f | cash=$%.2f",
            ticker, shares, price, self._cash,
        )
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
    # Bar-stream doorstuur (voor backward compat als iets rechtstreeks
    # subscribe_bars op de client aanroept — trader.py doet dit niet meer)
    # ------------------------------------------------------------------

    def subscribe_bars(
        self,
        tickers: List[str],
        on_bar: Callable[[str, float, float, float, float, float], None],
    ) -> None:
        if self._bar_stream is not None:
            self._bar_stream.subscribe_bars(tickers, on_bar)

    def start_stream(self) -> None:
        if self._bar_stream is not None:
            self._bar_stream.start_stream()

    def stop_stream(self) -> None:
        if self._bar_stream is not None:
            self._bar_stream.stop_stream()
