"""
IBKR API wrapper via ib_insync — orders en real-time bars.

Vereist IB Gateway of TWS draaiend op IBKR_HOST:IBKR_PORT.
Paper trading: poort 4002 (Gateway) of 7497 (TWS).
Live trading:  poort 4001 (Gateway) of 7496 (TWS).

OTC-filter: IBKR weigert veel OTC/pink-sheet aandelen voor EU-klanten
(MiFID II). is_tradable() controleert dit vooraf via contractdetails.

Architectuur:
  Alle ib_insync-aanroepen lopen in één vaste achtergrond-thread met
  een eigen asyncio event loop (_loop_thread). Flask-threads en andere
  threads lezen alleen gecachede waarden of plaatsen werk via
  asyncio.run_coroutine_threadsafe().
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Callable, Dict, List, Optional

from ib_insync import IB, MarketOrder, Stock, util


class IBKRClient:
    def __init__(self, host: str, port: int, client_id: int) -> None:
        self._host      = host
        self._port      = port
        self._client_id = client_id
        self._ib        = IB()
        self._bar_subs: Dict[str, object] = {}
        self._lock      = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_ready = threading.Event()
        self._cached_cash: float = 0.0
        util.logToConsole(logging.WARNING)

        # Start de vaste event-loop thread meteen
        self._loop_thread = threading.Thread(
            target=self._run_loop, daemon=True, name="ibkr-loop"
        )
        self._loop_thread.start()
        # Wacht tot de loop draait
        self._loop_ready.wait(timeout=5)

    # ------------------------------------------------------------------
    # Interne event-loop thread
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Achtergrond-thread: eigen asyncio loop + verbinding + cash poll."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._loop_ready.set()

        async def _main():
            while True:
                try:
                    if not self._ib.isConnected():
                        logging.info(
                            "IBKR verbinden op %s:%d (clientId=%d)...",
                            self._host, self._port, self._client_id,
                        )
                        await self._ib.connectAsync(
                            self._host, self._port, clientId=self._client_id
                        )
                        logging.info("IBKR verbonden.")
                        # Wacht tot IB Gateway account-data heeft gestuurd
                        await asyncio.sleep(3)

                    # IB Gateway stuurt automatisch account updates na connect
                    # Wacht tot de cache gevuld is (max 10s)
                    logging.info("IBKR wachten op account data...")
                    for _ in range(10):
                        vals = self._ib.accountValues()
                        if vals:
                            break
                        await asyncio.sleep(1)

                    logging.info("IBKR accountValues count: %d", len(vals))
                    found = False
                    # Probeer USD eerst, dan BASE (EUR-account)
                    for tag, currency in [
                        ("TotalCashValue",       "USD"),
                        ("CashBalance",          "USD"),
                        ("TotalCashValue",       "BASE"),
                        ("$LEDGER-CashBalance",  "BASE"),
                        ("TotalCashValue",       "EUR"),
                        ("$LEDGER-CashBalance",  "EUR"),
                    ]:
                        for v in vals:
                            if v.tag == tag and v.currency == currency:
                                self._cached_cash = float(v.value)
                                logging.info("IBKR cash bijgewerkt: %.2f %s (tag=%s)",
                                    self._cached_cash, currency, tag)
                                found = True
                                break
                        if found:
                            break
                    if not found:
                        logging.warning("IBKR cash niet gevonden — beschikbare tags: %s",
                            list({(v.tag, v.currency) for v in vals})[:10])

                    await asyncio.sleep(30)

                except Exception as exc:
                    logging.warning("IBKR loop fout: %s — herverbinden in 30s", exc, exc_info=True)
                    try:
                        self._ib.disconnect()
                    except Exception:
                        pass
                    await asyncio.sleep(30)

        loop.run_until_complete(_main())

    def _run_in_loop(self, coro):
        """Voer een coroutine uit vanuit een andere thread en wacht op het resultaat."""
        if self._loop is None:
            raise RuntimeError("IBKR event loop niet beschikbaar")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    # ------------------------------------------------------------------
    # Verbinding (publiek)
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Wordt automatisch opgeroepen door de achtergrond-thread.
        Handmatige aanroep wacht tot de achtergrond-thread verbonden is."""
        deadline = time.time() + 30
        while not self._ib.isConnected() and time.time() < deadline:
            time.sleep(0.5)
        if not self._ib.isConnected():
            raise TimeoutError("IBKR verbinding time-out")

    def disconnect(self) -> None:
        self._ib.disconnect()
        logging.info("IBKR verbinding verbroken.")

    def is_connected(self) -> bool:
        return self._ib.isConnected()

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_cash(self) -> float:
        """Gecachet saldo — bijgewerkt elke 30s door de achtergrond-thread."""
        return self._cached_cash

    def get_buying_power(self) -> float:
        vals = self._ib.accountValues()
        for v in vals:
            if v.tag == "BuyingPower" and v.currency == "USD":
                return float(v.value)
        return self._cached_cash

    # ------------------------------------------------------------------
    # OTC / MiFID II filter
    # ------------------------------------------------------------------

    def is_tradable(self, ticker: str) -> bool:
        contract = Stock(ticker, "SMART", "USD")
        try:
            details = self._run_in_loop(
                self._ib.reqContractDetailsAsync(contract)
            )
        except Exception as exc:
            logging.warning("Contractdetails mislukt voor %s: %s", ticker, exc)
            return False

        if not details:
            logging.info("OTC-filter: %s niet gevonden op IBKR → overgeslagen.", ticker)
            return False

        primary = (details[0].contract.primaryExch or "").upper()
        allowed = {"NYSE", "NASDAQ", "ARCA", "BATS", "IEX"}
        if primary not in allowed:
            logging.info(
                "OTC-filter: %s primaryExch=%s → overgeslagen (MiFID II).",
                ticker, primary,
            )
            return False

        return True

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def buy_market(self, ticker: str, shares: int) -> str:
        contract = Stock(ticker, "SMART", "USD")

        async def _place():
            await self._ib.qualifyContractsAsync(contract)
            order = MarketOrder("BUY", shares)
            trade = self._ib.placeOrder(contract, order)
            await asyncio.sleep(1)
            return str(trade.order.orderId)

        order_id = self._run_in_loop(_place())
        logging.info("BUY %s x%d  order_id=%s", ticker, shares, order_id)
        return order_id

    def sell_market(self, ticker: str, shares: int) -> str:
        contract = Stock(ticker, "SMART", "USD")

        async def _place():
            await self._ib.qualifyContractsAsync(contract)
            order = MarketOrder("SELL", shares)
            trade = self._ib.placeOrder(contract, order)
            await asyncio.sleep(1)
            return str(trade.order.orderId)

        order_id = self._run_in_loop(_place())
        logging.info("SELL %s x%d  order_id=%s", ticker, shares, order_id)
        return order_id

    def close_all_positions(self) -> None:
        async def _close():
            positions = self._ib.positions()
            for pos in positions:
                if pos.position == 0:
                    continue
                side  = "SELL" if pos.position > 0 else "BUY"
                qty   = abs(int(pos.position))
                order = MarketOrder(side, qty)
                self._ib.placeOrder(pos.contract, order)
                logging.info("EOD close: %s %s x%d", side, pos.contract.symbol, qty)
            logging.info("Alle posities gesloten (EOD).")

        self._run_in_loop(_close())

    def get_latest_price(self, ticker: str) -> Optional[float]:
        contract = Stock(ticker, "SMART", "USD")

        async def _fetch():
            await self._ib.qualifyContractsAsync(contract)
            td = self._ib.reqMktData(contract, "", True, False)
            await asyncio.sleep(2)
            price = td.last or td.close
            self._ib.cancelMktData(contract)
            return float(price) if price and price > 0 else None

        try:
            return self._run_in_loop(_fetch())
        except Exception as exc:
            logging.warning("Prijs ophalen mislukt voor %s: %s", ticker, exc)
            return None

    # ------------------------------------------------------------------
    # Real-time streaming (5-seconde bars → aggregeren naar 1m)
    # ------------------------------------------------------------------

    def subscribe_bars(
        self,
        tickers: List[str],
        on_bar: Callable[[str, float, float, float, float, float], None],
    ) -> None:
        async def _subscribe():
            for ticker in tickers:
                contract = Stock(ticker, "SMART", "USD")
                await self._ib.qualifyContractsAsync(contract)

                acc: Dict = {
                    "open": None, "high": -1e9, "low": 1e9,
                    "close": None, "volume": 0.0, "count": 0,
                }

                def make_handler(sym: str, accumulator: Dict):
                    def handler(bars, has_new_bar):
                        if not bars:
                            return
                        bar = bars[-1]
                        if accumulator["open"] is None:
                            accumulator["open"] = bar.open_
                        accumulator["high"]   = max(accumulator["high"],  bar.high)
                        accumulator["low"]    = min(accumulator["low"],   bar.low)
                        accumulator["close"]  = bar.close
                        accumulator["volume"] += bar.volume
                        accumulator["count"]  += 1

                        if accumulator["count"] >= 12:
                            on_bar(
                                sym,
                                accumulator["open"],
                                accumulator["high"],
                                accumulator["low"],
                                accumulator["close"],
                                accumulator["volume"],
                            )
                            accumulator.update({
                                "open": None, "high": -1e9, "low": 1e9,
                                "close": None, "volume": 0.0, "count": 0,
                            })
                    return handler

                bars = self._ib.reqRealTimeBars(contract, 5, "TRADES", False)
                bars.updateEvent += make_handler(ticker, acc)
                self._bar_subs[ticker] = bars
                logging.info("IBKR real-time bars: %s", ticker)

        self._run_in_loop(_subscribe())

    def start_stream(self) -> None:
        """Event loop draait al — geen aparte thread nodig."""
        logging.info("IBKR event loop actief (achtergrond-thread).")

    def stop_stream(self) -> None:
        async def _stop():
            for bars in self._bar_subs.values():
                try:
                    self._ib.cancelRealTimeBars(bars)
                except Exception:
                    pass

        try:
            self._run_in_loop(_stop())
        except Exception:
            pass
        logging.info("IBKR bar streams gestopt.")
