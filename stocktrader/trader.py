"""
Hoofdtrading loop — strategie uitvoering.

Modes (gestuurd via .env):
  BROKER=paper  + DATA_SOURCE=yfinance|polygon|alpaca → volledig gesimuleerd
  BROKER=t212   + DATA_SOURCE=alpaca                  → Alpaca data, T212 demo/live orders
  BROKER=t212   + T212_DEMO=true                      → T212 demo (geen echt geld)
  BROKER=t212   + T212_DEMO=false                     → T212 live (echt geld)

Flow per dag:
  09:30 ET → bar-stream start, ORB window opbouwen
  Na ORB   → breakout signalen, orders via actieve broker
  Continu  → stop-loss en target bewaken
  15:55 ET → EOD flatten
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Set
import zoneinfo

from .bar_stream import build_bar_stream
from .config import Settings
from .market_data import orb_avg_volume
from .notifier import Notifier
from .parser import Setup
from .state import ClosedTrade, DayState, Position, StateStore

ET = zoneinfo.ZoneInfo("America/New_York")
MARKET_OPEN_H  = 9
MARKET_OPEN_M  = 30
MARKET_CLOSE_H = 15
MARKET_CLOSE_M = 55

_DATA_STALE_BLOCK_FACTOR = 2  # blokkeer na 2× stale_bar_seconds zonder bar


def _build_broker_client(settings: Settings):
    """Maak de juiste broker-client op basis van BROKER-setting."""
    broker = settings.effective_broker()

    if broker == "t212":
        from .t212_client import T212Client
        return T212Client(
            api_key=settings.t212_api_key,
            api_secret=settings.t212_api_secret,
            demo=settings.t212_demo,
        )

    # paper (default)
    from .paper_client import PaperClient
    return PaperClient(
        start_capital=settings.paper_capital,
        poll_seconds=settings.bar_poll_seconds,
    )


class Trader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = _build_broker_client(settings)
        self._bar_stream = build_bar_stream(settings)

        broker_label = settings.effective_broker().upper()
        data_label   = settings.effective_data_source()
        logging.info(
            "Trader init | broker=%s | data=%s | poll=%ds",
            broker_label, data_label, settings.bar_poll_seconds,
        )

        self.notifier = Notifier(
            settings.telegram_enabled,
            settings.telegram_token,
            settings.telegram_chat_id,
        )
        self.store = StateStore(settings.state_dir)
        self._lock = threading.Lock()

        self._orb_volumes: Dict[str, List[float]] = defaultdict(list)
        self._orb_done: Dict[str, bool] = {}
        self._bar_count: Dict[str, int] = defaultdict(int)

        self._state: Optional[DayState] = None
        self._running = False
        self._engine_live = False
        self._loop_thread: Optional[threading.Thread] = None
        self._last_bar: Dict[str, float] = {}
        self._data_blocked: Set[str] = set()  # tickers tijdelijk geblokkeerd wegens stale data
        self._engine_started_at: float = 0.0
        self._last_bar_health_log: float = 0.0

    def load_day(self, state: DayState) -> None:
        with self._lock:
            self._state = state
            self.client.bind_state(self.store, state)
        logging.info("Dagstate geladen: %d setups", len(state.setups))

    def is_engine_live(self) -> bool:
        t = self._loop_thread
        return self._engine_live and t is not None and t.is_alive()

    def start(self, state: DayState) -> None:
        if self.is_engine_live():
            logging.info("Trader draait al — start overgeslagen.")
            return
        if self._loop_thread is not None and self._loop_thread.is_alive():
            logging.warning("Trader-thread start nog — dubbele start overgeslagen.")
            return
        self.load_day(state)
        self._running = True
        self._engine_live = False
        t = threading.Thread(target=self._run_loop, daemon=True, name="trader-loop")
        self._loop_thread = t
        t.start()
        logging.info("Trader gestart.")

    def stop(self) -> None:
        self._running = False
        self._engine_live = False
        self._bar_stream.stop_stream()

    def _run_loop(self) -> None:
        try:
            self._run_loop_inner()
        except Exception as exc:
            logging.error("Trading-loop onverwachte fout: %s", exc, exc_info=True)
            self.notifier.send(f"KRITIEK: trading-loop gecrasht: {exc}")
        finally:
            self._running = False
            self._engine_live = False
            with self._lock:
                state = self._state
            if state is not None:
                try:
                    state.active = False
                    self.store.save(state)
                except Exception:
                    pass

    def _run_loop_inner(self) -> None:
        setups = self._state.get_setups() if self._state else []
        if not setups:
            logging.warning("Geen setups geladen — trader stopt.")
            return

        self.client.connect()

        tradable: List[Setup] = []
        blocked: List[str] = []
        for s in setups:
            try:
                ok = self.client.is_tradable(s.ticker)
            except Exception as exc:
                logging.warning("Tradable-check mislukt voor %s: %s", s.ticker, exc)
                ok = False
            if ok:
                tradable.append(s)
            else:
                blocked.append(s.ticker)

        if blocked:
            logging.warning(
                "Geen data/toegang voor %d tickers (overgeslagen): %s", len(blocked), blocked
            )
            self.notifier.send(f"Overgeslagen (geen data/toegang): {', '.join(blocked)}")

        if not tradable:
            logging.warning("Geen verhandelbare setups — trader stopt.")
            self.notifier.send("Geen verhandelbare setups na data-check.")
            return

        tickers = [s.ticker for s in tradable]
        data_src = self.settings.effective_data_source()
        broker = self.settings.effective_broker()

        self._bar_stream.subscribe_bars(tickers, self._on_bar)
        self._bar_stream.start_stream()

        with self._lock:
            st = self._state
        cash = self._portfolio_cash(st) if st else self.settings.paper_capital

        t212_mode = ""
        if broker == "t212":
            t212_mode = " [DEMO]" if self.settings.t212_demo else " [LIVE]"

        msg = (
            f"Stocktrader gestart [{broker.upper()}{t212_mode}] | data={data_src} | "
            f"{len(tradable)} setups | Kapitaal: ${cash:.2f}\n" + ", ".join(tickers)
        )
        logging.info(msg)
        self.notifier.send(msg)

        self._engine_live = True
        self._last_bar = {}
        self._data_blocked = set()
        self._engine_started_at = time.monotonic()
        self._last_bar_health_log = 0.0
        stale_sec = self.settings.stale_bar_seconds()
        block_sec = stale_sec * _DATA_STALE_BLOCK_FACTOR
        _stale_warned: Set[str] = set()
        _STALE_GRACE_SEC = max(600, stale_sec)

        while self._running:
            now = datetime.now(ET)
            if now.hour > MARKET_CLOSE_H or (
                now.hour == MARKET_CLOSE_H and now.minute >= MARKET_CLOSE_M
            ):
                self._eod_exit()
                break

            if self._engine_live:
                now_mono = time.monotonic()
                uptime = now_mono - self._engine_started_at

                if now_mono - self._last_bar_health_log >= 300:
                    self._log_bar_health(tickers, stale_sec, data_src)
                    self._last_bar_health_log = now_mono

                if uptime >= _STALE_GRACE_SEC:
                    for tkr in tickers:
                        last_t = self._last_bar.get(tkr)
                        if last_t is None:
                            if tkr not in _stale_warned:
                                logging.warning(
                                    "STALE BAR: %s — nog geen nieuwe bar (data=%s)",
                                    tkr, data_src,
                                )
                                _stale_warned.add(tkr)
                            continue
                        age = now_mono - last_t
                        if age > stale_sec and tkr not in _stale_warned:
                            logging.warning(
                                "STALE BAR: %s — geen bar in %.0fs (limiet=%ds, data=%s)",
                                tkr, age, stale_sec, data_src,
                            )
                            _stale_warned.add(tkr)
                        elif age <= stale_sec and tkr in _stale_warned:
                            _stale_warned.discard(tkr)
                            if tkr in self._data_blocked:
                                self._data_blocked.discard(tkr)
                                logging.info("Data hersteld voor %s — blokkade opgeheven.", tkr)

                        # Blokkeer handel als data te lang oud is
                        if age > block_sec and tkr not in self._data_blocked:
                            self._data_blocked.add(tkr)
                            logging.warning(
                                "DATA BLOCK: %s geblokkeerd voor handel (geen bar in %.0fs).",
                                tkr, age,
                            )

                    received = sum(1 for t in tickers if t in self._last_bar)
                    if received > 0 and len(_stale_warned) >= len(tickers):
                        self.notifier.send(
                            f"ALARM: geen nieuwe bars in >{stale_sec}s voor alle tickers "
                            f"(data={data_src})."
                        )
                        _stale_warned.clear()

            time.sleep(15)

        self.stop()

    def _log_bar_health(self, tickers: List[str], stale_sec: int, data_src: str) -> None:
        now_mono = time.monotonic()
        parts = []
        for tkr in tickers:
            last_t = self._last_bar.get(tkr)
            blocked = " [BLOCKED]" if tkr in self._data_blocked else ""
            if last_t is None:
                parts.append(f"{tkr}:geen{blocked}")
            else:
                parts.append(f"{tkr}:{now_mono - last_t:.0f}s{blocked}")
        logging.info("Bar health (limiet=%ds, data=%s): %s", stale_sec, data_src, ", ".join(parts))

    def _on_bar(
        self,
        ticker: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        is_new_bar: bool = True,
    ) -> None:
        if is_new_bar:
            self._last_bar[ticker] = time.monotonic()
            # Hef data-blokkade op zodra er weer data binnenkomt
            if ticker in self._data_blocked:
                self._data_blocked.discard(ticker)
                logging.info("Data hersteld voor %s via binnenkomende bar.", ticker)
            # Zet prijs-cache bij op broker zodat get_latest_price up-to-date is
            if hasattr(self.client, "update_last_price"):
                self.client.update_last_price(ticker, close)

        with self._lock:
            if self._state is None:
                return

            state = self._state
            setup_map = {s.ticker: s for s in state.get_setups()}
            setup = setup_map.get(ticker)
            if setup is None:
                return

            self._bar_count[ticker] += 1
            bar_num = self._bar_count[ticker]

            logging.debug(
                "BAR #%d %s  O=%.4f H=%.4f L=%.4f C=%.4f V=%.0f%s",
                bar_num, ticker, open_, high, low, close, volume,
                "" if is_new_bar else " (snapshot)",
            )

            orb_min = self.settings.orb_minutes
            if orb_min > 0 and bar_num <= orb_min:
                self._orb_volumes[ticker].append(volume)
                if bar_num == orb_min:
                    self._orb_done[ticker] = True
                    avg = orb_avg_volume(self._orb_volumes[ticker])
                    logging.info("ORB klaar voor %s (avg vol=%.0f)", ticker, avg or 0)
                return

            orb_avg = orb_avg_volume(self._orb_volumes[ticker])
            positions = state.get_positions()

            if not is_new_bar:
                return

            # Sla trade-signalen over als data tijdelijk geblokkeerd is
            if ticker in self._data_blocked:
                logging.debug("BAR %s overgeslagen — data geblokkeerd.", ticker)
                return

            if ticker in positions:
                pos = positions[ticker]
                if low <= pos.stop_price:
                    logging.info("STOP %s | low=%.4f", ticker, low)
                    self._exit(state, pos, pos.stop_price, "STOP")
                elif high >= pos.target_price:
                    logging.info("T1 %s | high=%.4f", ticker, high)
                    self._exit(state, pos, pos.target_price, "T1")
                return

            closed_today = {t.ticker for t in state.get_closed_trades()}
            if ticker in closed_today:
                return

            vol_ok = (
                orb_avg is None
                or orb_avg == 0
                or volume >= self.settings.volume_mult * orb_avg
            )

            if high >= setup.break_:
                if vol_ok:
                    logging.info(
                        "BREAKOUT %s | high=%.4f >= break=%.4f | vol=%.0f",
                        ticker, high, setup.break_, volume,
                    )
                    self._enter(state, setup)
                else:
                    logging.info(
                        "BREAKOUT %s volume te laag | vol=%.0f need>=%.0f",
                        ticker, volume, (self.settings.volume_mult * orb_avg) if orb_avg else 0,
                    )

    def _portfolio_cash(self, state: DayState) -> float:
        return self.client.get_cash()

    def _cap_shares(self, shares: int, size_price: float) -> int:
        s = self.settings
        if s.max_order_usd > 0 and size_price > 0:
            shares = min(shares, int(s.max_order_usd / size_price))
        if s.max_shares_per_order > 0:
            shares = min(shares, s.max_shares_per_order)
        return shares

    def _record_position(
        self,
        state: DayState,
        setup: Setup,
        shares: int,
        entry_price: float,
        *,
        order_id: str,
        label: str,
        notify: bool,
    ) -> None:
        entry_price = entry_price if entry_price > 0 else setup.break_
        pos = Position(
            ticker=setup.ticker,
            shares=shares,
            entry_price=entry_price,
            stop_price=setup.hold,
            target_price=setup.t1,
            entry_time=datetime.now(ET).strftime("%H:%M"),
            order_id=order_id,
        )
        self.store.open_position(state, pos)
        max_loss = (entry_price - setup.hold) * shares
        msg = (
            f"{label} {setup.ticker} | {shares}x @ ${entry_price:.2f} | "
            f"Stop: ${setup.hold:.2f} | T1: ${setup.t1:.2f} | "
            f"Max verlies: ${max_loss:.2f}"
        )
        logging.info(msg)
        if notify:
            self.notifier.send(msg)

    def _enter(self, state: DayState, setup: Setup) -> None:
        s = self.settings

        if len(state.positions) >= s.max_positions:
            logging.info("Max posities (%d) — %s overgeslagen.", s.max_positions, setup.ticker)
            return

        cash = self._portfolio_cash(state)
        actual_price = self.client.get_latest_price(setup.ticker) or setup.break_
        size_price = max(actual_price, setup.break_)

        open_value = sum(
            p["entry_price"] * p["shares"] for p in state.positions.values()
        )
        portfolio = cash + open_value

        max_pos_pct = (
            s.max_position_pct_large
            if portfolio >= s.large_cap_threshold
            else s.max_position_pct
        )

        if portfolio >= s.risk_threshold_usd:
            stop_distance = setup.break_ - setup.hold
            if stop_distance <= 0:
                return
            risk_amount = portfolio * s.risk_per_trade_pct
            shares_by_risk = int(risk_amount / stop_distance)
            max_spend = portfolio * max_pos_pct
            shares_by_cap = int(max_spend / size_price)
            shares = min(shares_by_risk, shares_by_cap)
            mode = "RISK-BASED"
        else:
            available = cash * (1 - s.cash_reserve_pct)
            shares = int(available // size_price)
            mode = "ALL-IN"

        if shares < 1:
            logging.warning("Onvoldoende cash voor %s.", setup.ticker)
            return

        if shares * size_price > cash * (1 - s.cash_reserve_pct):
            shares = int(cash * (1 - s.cash_reserve_pct) // size_price)
            if shares < 1:
                return

        shares = self._cap_shares(shares, size_price)
        if shares < 1:
            return

        logging.info("ENTRY %s x%d @~%.4f [%s]", setup.ticker, shares, size_price, mode)
        try:
            order_id = self.client.buy_market(setup.ticker, shares)
        except Exception as exc:
            detail = str(exc).strip() or repr(exc)
            logging.error("Order mislukt %s: %s", setup.ticker, detail)
            self.notifier.send(f"ORDER MISLUKT {setup.ticker} x{shares}: {detail}")
            return

        fill_price = self.client.get_latest_price(setup.ticker) or size_price
        self._record_position(
            state, setup, shares, fill_price,
            order_id=order_id,
            label=f"ENTRY [{mode}]",
            notify=True,
        )

    def _exit(self, state: DayState, pos: Position, exit_price: float, reason: str) -> None:
        try:
            self.client.sell_market(pos.ticker, pos.shares)
        except Exception as exc:
            detail = str(exc).strip() or repr(exc)
            logging.error("Sell mislukt %s: %s", pos.ticker, detail)
            self.notifier.send(f"SELL MISLUKT {pos.ticker}: {detail}")
            return

        pnl = (exit_price - pos.entry_price) * pos.shares
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
        msg = (
            f"{emoji} {pos.ticker} | {pos.shares}x @ ${exit_price:.2f} | "
            f"PnL: ${pnl:+.2f} | {reason}"
        )
        logging.info(msg)
        self.notifier.send(msg)

    def _eod_exit(self) -> None:
        with self._lock:
            if self._state is None:
                return
            state = self._state
            positions = state.get_positions()

        if not positions:
            logging.info("EOD: geen open posities.")
            return

        logging.info("EOD: %d posities sluiten...", len(positions))
        self.notifier.send(f"EOD: {len(positions)} posities sluiten...")

        for ticker, pos in list(positions.items()):
            price = self.client.get_latest_price(ticker) or pos.entry_price
            for attempt in range(1, 4):
                try:
                    with self._lock:
                        self._exit(state, pos, price, "EOD")
                    break
                except Exception as exc:
                    if attempt < 3:
                        time.sleep(2)
                    else:
                        self.notifier.send(f"EOD EXIT MISLUKT {ticker}: {exc}")
