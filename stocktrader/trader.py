"""
Hoofdtrading loop — strategie uitvoering.

Flow per dag:
  09:30 ET → stream start, ORB window opbouwen
  Na ORB   → breakout signalen detecteren, orders plaatsen
  Continu  → stop-loss en target bewaken
  15:55 ET → alle posities sluiten (EOD)
  15:59 ET → stream stoppen
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional
import zoneinfo

from .paper_client import PaperClient
from .config import Settings
from .notifier import Notifier
from .parser import Setup
from .state import ClosedTrade, DayState, Position, StateStore

ET = zoneinfo.ZoneInfo("America/New_York")
MARKET_OPEN_H  = 9
MARKET_OPEN_M  = 30
MARKET_CLOSE_H = 15
MARKET_CLOSE_M = 55   # 4 minuten voor sluit → EOD exit


class Trader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        if settings.paper_mode:
            self.ibkr = PaperClient(
                start_capital=settings.paper_capital,
                data_source=settings.data_source,
                polygon_api_key=settings.polygon_api_key,
            )
            logging.info("Paper mode actief (data=%s, kapitaal=$%.2f)", settings.data_source, settings.paper_capital)
        else:
            from .ibkr_client import IBKRClient   # lazy import — vereist ib_insync
            self.ibkr = IBKRClient(
                settings.ibkr_host,
                settings.ibkr_port,
                settings.ibkr_client_id,
                otc_filter_enabled=settings.otc_filter_enabled,
            )
            logging.info("Live mode actief (IBKR %s:%d)", settings.ibkr_host, settings.ibkr_port)
        self.notifier  = Notifier(
            settings.telegram_enabled,
            settings.telegram_token,
            settings.telegram_chat_id,
        )
        self.store     = StateStore(settings.state_dir)
        self._lock     = threading.Lock()

        # ORB state per ticker: lijst van volumes tijdens ORB window
        self._orb_volumes: Dict[str, List[float]] = defaultdict(list)
        self._orb_done:    Dict[str, bool]         = {}
        self._bar_count:   Dict[str, int]          = defaultdict(int)

        self._state: Optional[DayState] = None
        self._running = False

    # ------------------------------------------------------------------
    # Publieke interface
    # ------------------------------------------------------------------

    def load_day(self, state: DayState) -> None:
        """Laad de dagstate (wordt aangeroepen door dashboard na upload)."""
        with self._lock:
            self._state = state
            # Koppel cash persistentie in paper mode
            if self.settings.paper_mode and isinstance(self.ibkr, PaperClient):
                self.ibkr.bind_state(self.store, state)
        logging.info("Dagstate geladen: %d setups", len(state.setups))

    def start(self, state: DayState) -> None:
        """Start de tradingloop voor vandaag."""
        self.load_day(state)
        self._running = True
        t = threading.Thread(target=self._run_loop, daemon=True)
        t.start()
        logging.info("Trader gestart.")

    def stop(self) -> None:
        self._running = False
        self.ibkr.stop_stream()
        # Verbinding blijft actief voor dashboard cash-polling

    # ------------------------------------------------------------------
    # Hoofdloop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        setups = self._state.get_setups() if self._state else []
        if not setups:
            logging.warning("Geen setups geladen — trader stopt.")
            return

        # Verbinding maken met IB Gateway
        try:
            self.ibkr.connect()
        except Exception as exc:
            logging.error("IBKR verbinding mislukt: %s", exc)
            self.notifier.send(f"IBKR verbinding mislukt: {exc}")
            return

        # OTC-filter: verwijder aandelen die IBKR niet toelaat (MiFID II)
        tradable = []
        blocked  = []
        for s in setups:
            try:
                ok = self.ibkr.is_tradable(s.ticker)
            except Exception as exc:
                logging.warning("Tradable-check mislukt voor %s: %s", s.ticker, exc)
                ok = False
            if ok:
                tradable.append(s)
            else:
                blocked.append(s.ticker)

        if blocked:
            logging.warning("OTC-filter: %d tickers overgeslagen: %s", len(blocked), blocked)
            self.notifier.send(f"OTC-filter: {', '.join(blocked)} overgeslagen (niet verhandelbaar via IBKR)")

        if not tradable:
            logging.warning(
                "Geen verhandelbare setups na OTC-filter (%d geparsed, %d geblokkeerd: %s) — trader stopt.",
                len(setups), len(blocked), blocked,
            )
            self.notifier.send(
                f"Geen verhandelbare setups na OTC-filter. "
                f"Geladen: {len(setups)} ({', '.join(s.ticker for s in setups)}). "
                f"Geblokkeerd: {', '.join(blocked) or '—'}."
            )
            return

        tickers   = [s.ticker for s in tradable]
        setup_map: Dict[str, Setup] = {s.ticker: s for s in tradable}

        # Abonneer op 1m bars
        self.ibkr.subscribe_bars(tickers, self._on_bar)
        self.ibkr.start_stream()

        mode = "paper" if self.settings.paper_mode else "LIVE"
        cash = self.ibkr.get_cash()
        msg  = (
            f"Stocktrader gestart [{mode}] | {len(setups)} setups | "
            f"Cash: ${cash:.2f}\n"
            + ", ".join(tickers)
        )
        logging.info(msg)
        self.notifier.send(msg)

        # Wacht tot EOD exit tijd
        while self._running:
            now = datetime.now(ET)
            if now.hour > MARKET_CLOSE_H or (
                now.hour == MARKET_CLOSE_H and now.minute >= MARKET_CLOSE_M
            ):
                self._eod_exit()
                break
            time.sleep(15)

        self.stop()

    # ------------------------------------------------------------------
    # Bar handler (real-time 1m candles)
    # ------------------------------------------------------------------

    def _on_bar(
        self,
        ticker: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        with self._lock:
            if self._state is None:
                return

            state     = self._state
            setup_map = {s.ticker: s for s in state.get_setups()}
            setup     = setup_map.get(ticker)
            if setup is None:
                return

            self._bar_count[ticker] += 1
            bar_num = self._bar_count[ticker]

            logging.debug(
                "BAR #%d %s  O=%.4f H=%.4f L=%.4f C=%.4f V=%.0f",
                bar_num, ticker, open_, high, low, close, volume,
            )

            # ORB window opbouwen
            orb_min = self.settings.orb_minutes
            if orb_min > 0 and bar_num <= orb_min:
                self._orb_volumes[ticker].append(volume)
                if bar_num == orb_min:
                    self._orb_done[ticker] = True
                    logging.info("ORB klaar voor %s (avg vol=%.0f)", ticker,
                        sum(self._orb_volumes[ticker]) / len(self._orb_volumes[ticker]))
                return  # geen trades tijdens ORB window

            orb_avg = (
                sum(self._orb_volumes[ticker]) / len(self._orb_volumes[ticker])
                if self._orb_volumes[ticker] else None
            )

            positions = state.get_positions()

            # --- EXIT: stop of target ---
            if ticker in positions:
                pos = positions[ticker]
                if low <= pos.stop_price:
                    logging.info("STOP geraakt voor %s | low=%.4f <= stop=%.4f", ticker, low, pos.stop_price)
                    self._exit(state, pos, pos.stop_price, "STOP")
                elif high >= pos.target_price:
                    logging.info("TARGET geraakt voor %s | high=%.4f >= t1=%.4f", ticker, high, pos.target_price)
                    self._exit(state, pos, pos.target_price, "T1")
                return

            # --- ENTRY: breakout check ---
            if ticker in {t.ticker for t in state.get_closed_trades()}:
                return  # al gehandeld vandaag

            vol_ok = (
                orb_avg is None
                or orb_avg == 0
                or volume >= self.settings.volume_mult * orb_avg
            )

            if high >= setup.break_:
                if vol_ok:
                    logging.info("BREAKOUT %s | high=%.4f >= break=%.4f | vol=%.0f", ticker, high, setup.break_, volume)
                    self._enter(state, setup)
                else:
                    logging.info("BREAKOUT %s GEBLOKKEERD (volume te laag) | vol=%.0f orb_avg=%.0f mult=%.1f",
                        ticker, volume, orb_avg, self.settings.volume_mult)

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------

    def _enter(self, state: DayState, setup: Setup) -> None:
        s = self.settings

        # Max posities check
        if len(state.positions) >= s.max_positions:
            logging.info("Max posities (%d) bereikt — %s overgeslagen.", s.max_positions, setup.ticker)
            return

        cash     = self.ibkr.get_cash()

        # Gebruik actuele prijs voor sizing (niet setup.break_ — die kan lager zijn dan markt)
        actual_price = self.ibkr.get_latest_price(setup.ticker) or setup.break_
        size_price   = max(actual_price, setup.break_)

        # Portfolio waarde = cash + marktwaarde open posities (benadering: entry * shares)
        open_value = sum(
            p["entry_price"] * p["shares"]
            for p in state.positions.values()
        )
        portfolio = cash + open_value

        above_threshold = portfolio >= s.risk_threshold_usd
        max_pos_pct = s.max_position_pct_large if portfolio >= s.large_cap_threshold else s.max_position_pct

        if above_threshold:
            # Risico-based sizing
            stop_distance = setup.break_ - setup.hold
            if stop_distance <= 0:
                return
            risk_amount   = portfolio * s.risk_per_trade_pct
            shares_by_risk = int(risk_amount / stop_distance)

            # Cap op max_position_pct van portfolio
            max_spend     = portfolio * max_pos_pct
            shares_by_cap = int(max_spend / size_price)

            shares = min(shares_by_risk, shares_by_cap)
            mode   = "RISK-BASED"
        else:
            # All-in onder drempel
            available = cash * (1 - s.cash_reserve_pct)
            shares    = int(available // size_price)
            mode      = "ALL-IN"

        if shares < 1:
            logging.warning(
                "Onvoldoende cash voor %s | portfolio=%.2f cash=%.2f prijs=%.2f [%s]",
                setup.ticker, portfolio, cash, size_price, mode,
            )
            return

        spend = shares * size_price
        if spend > cash * (1 - s.cash_reserve_pct):
            shares = int(cash * (1 - s.cash_reserve_pct) // size_price)
            if shares < 1:
                logging.warning("Na herberekening onvoldoende cash voor %s.", setup.ticker)
                return

        try:
            order_id = self.ibkr.buy_market(setup.ticker, shares)
        except Exception as exc:
            logging.error("Order mislukt voor %s: %s", setup.ticker, exc)
            self.notifier.send(f"ORDER MISLUKT {setup.ticker}: {exc}")
            return

        pos = Position(
            ticker=setup.ticker,
            shares=shares,
            entry_price=setup.break_,
            stop_price=setup.hold,
            target_price=setup.t1,
            entry_time=datetime.now(ET).strftime("%H:%M"),
            order_id=order_id,
        )
        self.store.open_position(state, pos)

        max_loss = (setup.break_ - setup.hold) * shares
        msg = (
            f"ENTRY {setup.ticker} [{mode}] | {shares}x @ ${setup.break_:.2f} | "
            f"Stop: ${setup.hold:.2f} | T1: ${setup.t1:.2f} | "
            f"Max verlies: ${max_loss:.2f} | R:R {setup.rr_t1():.1f}x | "
            f"Portfolio: ${portfolio:.2f}"
        )
        logging.info(msg)
        self.notifier.send(msg)

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------

    def _exit(self, state: DayState, pos: Position, exit_price: float, reason: str) -> None:
        try:
            self.ibkr.sell_market(pos.ticker, pos.shares)
        except Exception as exc:
            logging.error("Sell mislukt voor %s: %s", pos.ticker, exc)
            self.notifier.send(f"SELL MISLUKT {pos.ticker}: {exc}")
            return

        pnl   = (exit_price - pos.entry_price) * pos.shares
        trade = ClosedTrade(
            ticker=pos.ticker,
            shares=pos.shares,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=datetime.now(ET).strftime("%H:%M"),
            reason=reason,
            pnl=round(pnl, 2),
        )
        self.store.close_position(state, trade)

        emoji = "WIN" if pnl >= 0 else "STOP"
        msg   = (
            f"{emoji} {pos.ticker} | {pos.shares}x @ ${exit_price:.2f} | "
            f"PnL: ${pnl:+.2f} | Reden: {reason}"
        )
        logging.info(msg)
        self.notifier.send(msg)

    # ------------------------------------------------------------------
    # EOD
    # ------------------------------------------------------------------

    def _eod_exit(self) -> None:
        with self._lock:
            if self._state is None:
                return
            state     = self._state
            positions = state.get_positions()

        if not positions:
            logging.info("EOD: geen open posities.")
            return

        logging.info("EOD: %d posities sluiten...", len(positions))
        self.notifier.send(f"EOD: {len(positions)} posities sluiten...")

        for ticker, pos in positions.items():
            price = self.ibkr.get_latest_price(ticker) or pos.entry_price
            with self._lock:
                self._exit(state, pos, price, "EOD")
