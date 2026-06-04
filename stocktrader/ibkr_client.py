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
import concurrent.futures
import logging
import threading
import time
from typing import Callable, Dict, List, Optional

from ib_insync import IB, MarketOrder, Stock, util


class IBKRClient:
    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        *,
        otc_filter_enabled: bool = True,
        market_data_type: int = 3,
        bar_stream_mode: str = "historical",
        max_order_shares: int = 500,
    ) -> None:
        self._host      = host
        self._port      = port
        self._client_id = client_id
        self._otc_filter_enabled = otc_filter_enabled
        self._market_data_type = market_data_type
        self._bar_stream_mode = bar_stream_mode.lower()
        self._max_order_shares = max(0, max_order_shares)

    @property
    def _order_chunk_size(self) -> int:
        """Max stuks per placeOrder (IBKR weigert/gecancel grote market orders)."""
        return self._max_order_shares if self._max_order_shares > 0 else 500
        self._ib        = IB()
        self._bar_subs: Dict[str, object] = {}
        self._mdt_applied = False
        self._lock      = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_ready = threading.Event()
        self._cached_cash: float = 0.0
        util.logToConsole(logging.WARNING)
        # ib_insync bar handlers draaien op de event-loop; strategie niet synchroon daar
        self._bar_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ibkr-bar-dispatch",
        )

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
                        self._apply_market_data_type()
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

    def _run_in_loop(self, coro, timeout: float = 30):
        """Voer een coroutine uit vanuit een andere thread en wacht op het resultaat."""
        if self._loop is None:
            raise RuntimeError("IBKR event loop niet beschikbaar")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except TimeoutError as exc:
            raise RuntimeError(
                f"IBKR event loop timeout na {timeout:.0f}s "
                f"(loop mogelijk overbelast door bar-streams)"
            ) from exc

    def _apply_market_data_type(self) -> None:
        """1=live, 3=delayed (~15min, vaak zonder betaald NASDAQ/AMEX RT pakket)."""
        labels = {1: "live", 2: "frozen", 3: "delayed", 4: "delayed_frozen"}
        try:
            self._ib.reqMarketDataType(self._market_data_type)
            self._mdt_applied = True
            logging.info(
                "IBKR market data type: %s (%d)",
                labels.get(self._market_data_type, "?"),
                self._market_data_type,
            )
        except Exception as exc:
            logging.warning("reqMarketDataType mislukt: %s", exc)

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

    def get_stock_positions(self) -> Dict[str, dict]:
        """Open US-aandelenposities bij IBKR: symbol → shares, avg_cost, side."""

        async def _fetch():
            if self._ib.isConnected():
                self._ib.reqPositions()
                await asyncio.sleep(1)
            out: Dict[str, dict] = {}
            for pos in self._ib.positions():
                c = pos.contract
                if getattr(c, "secType", "") != "STK":
                    continue
                qty = int(pos.position)
                if qty == 0:
                    continue
                sym = c.symbol
                avg = float(pos.avgCost or 0)
                if avg <= 0 and getattr(pos, "averageCost", None):
                    avg = float(pos.averageCost)
                out[sym] = {
                    "shares": abs(qty),
                    "side": "long" if qty > 0 else "short",
                    "avg_cost": avg,
                }
            return out

        return self._run_in_loop(_fetch(), timeout=20)

    # ------------------------------------------------------------------
    # OTC / MiFID II filter
    # ------------------------------------------------------------------

    # Exchanges die IBKR/EU meestal blokkeert (MiFID II / OTC)
    _BLOCKED_EXCHANGES = frozenset({
        "OTC", "OTCBB", "PINK", "GREY", "EXPERT", "IBEOS", "OTCQB", "OTCQX",
    })

    @staticmethod
    def _primary_exchange(contract) -> str:
        """ib_insync: attribuut heet primaryExchange (niet primaryExch)."""
        val = getattr(contract, "primaryExchange", None) or getattr(
            contract, "primaryExch", None
        )
        return (val or "").upper()

    def _contract_exists(self, ticker: str) -> bool:
        """Symbool bekend bij IBKR (geen OTC-check)."""
        contract = Stock(ticker, "SMART", "USD")
        try:
            qualified = self._run_in_loop(
                self._ib.qualifyContractsAsync(contract)
            )
            if qualified:
                return True
            details = self._run_in_loop(
                self._ib.reqContractDetailsAsync(contract)
            )
            return bool(details)
        except Exception as exc:
            logging.warning("Symbool-check mislukt voor %s: %s", ticker, exc)
            return False

    def is_tradable(self, ticker: str) -> bool:
        """
        True als IBKR het symbool kent en de primaire beurs geen OTC/PINK is.

        Let op: validExchanges bevat vaak ook 'OTC' als route — die negeren we.
        Alleen primaryExchange telt (NYSE, NASDAQ, ISLAND, leeg, etc.).
        """
        if not self._otc_filter_enabled:
            return self._contract_exists(ticker)

        contract = Stock(ticker, "SMART", "USD")
        try:
            qualified = self._run_in_loop(
                self._ib.qualifyContractsAsync(contract)
            )
        except Exception as exc:
            logging.warning("qualify mislukt voor %s: %s", ticker, exc)
            qualified = []

        if qualified:
            c = qualified[0]
            primary = self._primary_exchange(c)
            if primary in self._BLOCKED_EXCHANGES:
                logging.info(
                    "OTC-filter: %s geblokkeerd (primaryExchange=%s)", ticker, primary
                )
                return False
            logging.info(
                "OTC-filter: %s OK (primaryExchange=%s)", ticker, primary or "SMART"
            )
            return True

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

        primaries: list[str] = []
        for d in details:
            c = d.contract
            if c.secType != "STK" or c.currency != "USD":
                continue
            primary = self._primary_exchange(c)
            primaries.append(primary or "—")
            if primary in self._BLOCKED_EXCHANGES:
                continue
            logging.info(
                "OTC-filter: %s OK (primaryExchange=%s)", ticker, primary or "—"
            )
            return True

        logging.info(
            "OTC-filter: %s → overgeslagen (alleen OTC: %s)",
            ticker, ", ".join(dict.fromkeys(primaries)) or "?",
        )
        return False

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    @staticmethod
    def _chunk_shares(total: int, chunk_size: int) -> List[int]:
        if chunk_size <= 0 or total <= chunk_size:
            return [total]
        parts: List[int] = []
        left = total
        while left > 0:
            q = min(chunk_size, left)
            parts.append(q)
            left -= q
        return parts

    @staticmethod
    def _order_error_detail(trade) -> str:
        """IBKR reject/cancel reden uit trade.log en orderStatus."""
        status = getattr(trade.orderStatus, "status", "") or ""
        why = getattr(trade.orderStatus, "whyHeld", "") or ""
        parts = [p for p in (status, why) if p]
        for entry in reversed(trade.log or []):
            msg = getattr(entry, "message", None) or str(entry)
            if msg and msg not in parts:
                parts.append(msg)
        return " | ".join(parts) if parts else "geen status van IBKR (check Gateway logs)"

    def buy_market(self, ticker: str, shares: int) -> str:
        chunks = self._chunk_shares(shares, self._order_chunk_size)
        if len(chunks) > 1:
            logging.info(
                "BUY %s x%d in %d orders (max %d/share/order, IBKR-limiet)",
                ticker, shares, len(chunks), self._order_chunk_size,
            )
        timeout = max(60.0, len(chunks) * 10.0)
        return self._run_in_loop(self._place_market_chunks(ticker, "BUY", chunks), timeout=timeout)

    def sell_market(self, ticker: str, shares: int) -> str:
        chunks = self._chunk_shares(shares, self._order_chunk_size)
        if len(chunks) > 1:
            logging.info(
                "SELL %s x%d in %d orders (max %d/share/order, IBKR-limiet)",
                ticker, shares, len(chunks), self._order_chunk_size,
            )
        timeout = max(60.0, len(chunks) * 10.0)
        return self._run_in_loop(self._place_market_chunks(ticker, "SELL", chunks), timeout=timeout)

    async def _place_market_chunks(
        self, ticker: str, side: str, chunks: List[int],
    ) -> str:
        contract = Stock(ticker, "SMART", "USD")
        qualified = await self._ib.qualifyContractsAsync(contract)
        if not qualified:
            raise RuntimeError(f"contract niet gekwalificeerd: {ticker}")
        c = qualified[0]
        order_ids: List[str] = []
        n = len(chunks)
        for i, qty in enumerate(chunks, start=1):
            qty = min(qty, self._order_chunk_size)
            order = MarketOrder(side, qty)
            trade = self._ib.placeOrder(c, order)
            for _ in range(25):
                st = (trade.orderStatus.status or "").upper()
                if st == "FILLED":
                    break
                if st in ("CANCELLED", "INACTIVE", "APICANCELLED"):
                    raise RuntimeError(self._order_error_detail(trade))
                await asyncio.sleep(0.2)
            else:
                st = (trade.orderStatus.status or "").upper()
                if st != "FILLED":
                    raise RuntimeError(
                        f"order timeout status={st}: {self._order_error_detail(trade)}"
                    )
            oid = str(trade.order.orderId)
            order_ids.append(oid)
            logging.info("%s %s deel %d/%d x%d order_id=%s", side, ticker, i, n, qty, oid)
            if i < n:
                await asyncio.sleep(0.35)
        return ",".join(order_ids)

    def close_all_positions(self) -> None:
        """Sluit posities in chunks (zelfde limiet als buy/sell_market)."""

        async def _close():
            positions = self._ib.positions()
            for pos in positions:
                if pos.position == 0:
                    continue
                sym = pos.contract.symbol
                side = "SELL" if pos.position > 0 else "BUY"
                qty = abs(int(pos.position))
                chunks = self._chunk_shares(qty, self._order_chunk_size)
                for i, part in enumerate(chunks, start=1):
                    order = MarketOrder(side, part)
                    self._ib.placeOrder(pos.contract, order)
                    logging.info(
                        "EOD close: %s %s x%d (%d/%d)", side, sym, part, i, len(chunks),
                    )
                    await asyncio.sleep(0.35)
            logging.info("Alle posities gesloten (EOD).")

        self._run_in_loop(_close())

    def get_latest_price(self, ticker: str) -> Optional[float]:
        contract = Stock(ticker, "SMART", "USD")

        async def _fetch():
            self._apply_market_data_type()
            await self._ib.qualifyContractsAsync(contract)
            td = self._ib.reqMktData(contract, "", True, False)
            await asyncio.sleep(2)
            price = td.last or td.close
            self._ib.cancelMktData(contract)
            return float(price) if price and price > 0 else None

        try:
            return self._run_in_loop(_fetch())
        except Exception as exc:
            detail = str(exc).strip() or repr(exc)
            logging.warning("Prijs ophalen mislukt voor %s: %s", ticker, detail)
            return None

    def _dispatch_bar(
        self,
        on_bar: Callable[..., None],
        ticker: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        *,
        is_new_bar: bool,
    ) -> None:
        """Strategie op worker-thread — voorkomt deadlock met _run_in_loop."""
        self._bar_executor.submit(
            self._run_bar_callback,
            on_bar, ticker, open_, high, low, close, volume, is_new_bar,
        )

    @staticmethod
    def _run_bar_callback(
        on_bar: Callable[..., None],
        ticker: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        is_new_bar: bool,
    ) -> None:
        try:
            on_bar(ticker, open_, high, low, close, volume, is_new_bar)
        except Exception as exc:
            logging.error(
                "Bar callback fout %s: %s", ticker, str(exc).strip() or repr(exc),
                exc_info=True,
            )

    @staticmethod
    def _pick_hist_bar(bars, has_new_bar: bool):
        """Voltooide bar: bij update [-2], bij eerste snapshot [-1]."""
        if not bars:
            return None
        if has_new_bar and len(bars) >= 2:
            return bars[-2]
        return bars[-1]

    # ------------------------------------------------------------------
    # Bar streaming — historical 1m (default) of realtime 5s→1m
    # ------------------------------------------------------------------

    def subscribe_bars(
        self,
        tickers: List[str],
        on_bar: Callable[[str, float, float, float, float, float], None],
    ) -> None:
        if self._bar_stream_mode == "realtime":
            self._run_in_loop(
                self._subscribe_realtime_bars(tickers, on_bar),
                timeout=max(60, len(tickers) * 5),
            )
        else:
            self._run_in_loop(
                self._subscribe_historical_bars(tickers, on_bar),
                timeout=max(120, len(tickers) * 10),
            )

    async def _subscribe_historical_bars(
        self,
        tickers: List[str],
        on_bar: Callable[[str, float, float, float, float, float], None],
    ) -> None:
        """1-min bars via keepUpToDate — werkt met delayed data (geen Error 420)."""
        self._apply_market_data_type()
        logging.info(
            "IBKR 1m historical stream (delayed OK) voor %d tickers", len(tickers)
        )

        last_bar_key: Dict[str, str] = {}

        for ticker in tickers:
            contract = Stock(ticker, "SMART", "USD")
            qualified = await self._ib.qualifyContractsAsync(contract)
            if not qualified:
                logging.warning("IBKR historical: %s niet gekwalificeerd", ticker)
                continue
            contract = qualified[0]

            def make_handler(sym: str):
                def handler(bars, has_new_bar):
                    bar = self._pick_hist_bar(bars, has_new_bar)
                    if bar is None:
                        return
                    key = str(bar.date)
                    if last_bar_key.get(sym) == key:
                        return
                    last_bar_key[sym] = key
                    logging.info(
                        "IBKR bar %s %s H=%.4f V=%.0f (has_new_bar=%s)",
                        sym, key, float(bar.high), float(bar.volume), has_new_bar,
                    )
                    self._dispatch_bar(
                        on_bar,
                        sym,
                        float(bar.open),
                        float(bar.high),
                        float(bar.low),
                        float(bar.close),
                        float(bar.volume),
                        is_new_bar=has_new_bar,
                    )
                return handler

            bars = await self._ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr="1 D",
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
                keepUpToDate=True,
            )
            bars.updateEvent += make_handler(ticker)
            self._bar_subs[ticker] = bars
            logging.info(
                "IBKR 1m historical (keepUpToDate): %s (%d bars geladen)",
                ticker, len(bars),
            )
            # Eerste load: snapshot voor logging/ORB; geen entry (is_new_bar=False)
            if bars:
                bar = self._pick_hist_bar(bars, False)
                if bar is not None:
                    key = str(bar.date)
                    last_bar_key[ticker] = key
                    logging.info(
                        "IBKR bar %s %s H=%.4f V=%.0f (snapshot)",
                        ticker, key, float(bar.high), float(bar.volume),
                    )
                    self._dispatch_bar(
                        on_bar,
                        ticker,
                        float(bar.open),
                        float(bar.high),
                        float(bar.low),
                        float(bar.close),
                        float(bar.volume),
                        is_new_bar=False,
                    )
            await asyncio.sleep(0.35)

    async def _subscribe_realtime_bars(
        self,
        tickers: List[str],
        on_bar: Callable[[str, float, float, float, float, float], None],
    ) -> None:
        """5s real-time bars — vereist betaald US equity RT market data abonnement."""
        self._apply_market_data_type()
        logging.info("IBKR 5s realtime bars voor %d tickers", len(tickers))

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
                        self._dispatch_bar(
                            on_bar,
                            sym,
                            accumulator["open"],
                            accumulator["high"],
                            accumulator["low"],
                            accumulator["close"],
                            accumulator["volume"],
                            is_new_bar=True,
                        )
                        accumulator.update({
                            "open": None, "high": -1e9, "low": 1e9,
                            "close": None, "volume": 0.0, "count": 0,
                        })
                return handler

            rt = self._ib.reqRealTimeBars(contract, 5, "TRADES", False)
            rt.updateEvent += make_handler(ticker, acc)
            self._bar_subs[ticker] = rt
            logging.info("IBKR real-time bars: %s", ticker)
            await asyncio.sleep(0.2)

    def start_stream(self) -> None:
        """Event loop draait al — geen aparte thread nodig."""
        logging.info("IBKR event loop actief (achtergrond-thread).")

    def stop_stream(self) -> None:
        async def _stop():
            for sym, bars in list(self._bar_subs.items()):
                try:
                    if self._bar_stream_mode == "realtime":
                        self._ib.cancelRealTimeBars(bars)
                    else:
                        self._ib.cancelHistoricalData(bars)
                except Exception:
                    pass
            self._bar_subs.clear()

        try:
            self._run_in_loop(_stop())
        except Exception:
            pass
        logging.info("IBKR bar streams gestopt.")
