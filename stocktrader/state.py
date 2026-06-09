"""
Dagelijkse state — watchlist, posities, trades.
Persisteert naar JSON zodat een herstart geen data verliest.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

# Module-level lock: beschermt tegen concurrent writes van dashboard + trader threads
_STATE_LOCK = threading.Lock()


def trading_date() -> date:
    """Handelsdag in ET — niet de server-systeemtijd."""
    return datetime.now(_ET).date()

from .parser import Setup


@dataclass
class Position:
    ticker:       str
    shares:       int
    entry_price:  float
    stop_price:   float
    target_price: float
    entry_time:   str
    order_id:     str
    t2_price:     float = 0.0


@dataclass
class ClosedTrade:
    ticker:      str
    shares:      int
    entry_price: float
    exit_price:  float
    entry_time:  str
    exit_time:   str
    reason:      str   # "T1", "T2", "STOP", "EOD", "MANUAL"
    pnl:         float


@dataclass
class DayState:
    trade_date:   str
    setups:       List[dict]
    positions:    Dict[str, dict]
    closed_trades: List[dict]
    active:       bool
    cash:         float = 0.0   # huidig cash saldo (gepersisteerd)
    crashed:      bool = False  # True als trading-loop onverwacht crashte

    @staticmethod
    def empty(trade_date: date, start_capital: float = 0.0) -> "DayState":
        return DayState(
            trade_date=trade_date.isoformat(),
            setups=[],
            positions={},
            closed_trades=[],
            active=False,
            cash=start_capital,
            crashed=False,
        )

    def get_setups(self) -> List[Setup]:
        result = []
        for d in self.setups:
            result.append(Setup(
                ticker=d["ticker"],
                hold=d["hold"],
                break_=d["break_"],
                t1=d["t1"],
                t2=d["t2"],
            ))
        return result

    def get_positions(self) -> Dict[str, Position]:
        return {
            ticker: Position(**{**pos, "t2_price": pos.get("t2_price", 0.0)})
            for ticker, pos in self.positions.items()
        }

    def get_closed_trades(self) -> List[ClosedTrade]:
        return [ClosedTrade(**t) for t in self.closed_trades]


class StateStore:
    def __init__(self, state_dir: str) -> None:
        self.path = Path(state_dir)
        self.path.mkdir(parents=True, exist_ok=True)

    def _file(self, trade_date: date) -> Path:
        return self.path / f"{trade_date.isoformat()}.json"

    def list_trade_dates(self) -> List[date]:
        """Alle dagen met opgeslagen state (nieuwste eerst)."""
        dates: List[date] = []
        for f in self.path.glob("*.json"):
            try:
                dates.append(date.fromisoformat(f.stem))
            except ValueError:
                continue
        dates.sort(reverse=True)
        return dates

    def load_date(self, trade_date: date, start_capital: float = 0.0) -> Optional[DayState]:
        """Laad state voor een datum; None als er geen bestand is."""
        if not self._file(trade_date).exists():
            return None
        return self.load(trade_date, start_capital)

    def day_summary(self, trade_date: date) -> Optional[dict]:
        """Samenvatting voor historiek-overzicht."""
        state = self.load_date(trade_date)
        if state is None:
            return None
        trades = state.closed_trades
        day_pnl = sum(float(t.get("pnl", 0)) for t in trades)
        return {
            "date": trade_date.isoformat(),
            "trade_count": len(trades),
            "day_pnl": day_pnl,
            "cash": state.cash,
            "open_positions": len(state.positions),
        }

    def load(self, trade_date: date, start_capital: float = 0.0) -> DayState:
        f = self._file(trade_date)
        if not f.exists():
            return DayState.empty(trade_date, start_capital)
        try:
            with open(f) as fp:
                data = json.load(fp)
        except json.JSONDecodeError as exc:
            logging.error("State JSON corrupt (%s): %s — leeg state aangemaakt.", f, exc)
            return DayState.empty(trade_date, start_capital)
        # backwards compat: oude state zonder cash/crashed veld
        if "cash" not in data:
            data["cash"] = start_capital
        if "crashed" not in data:
            data["crashed"] = False
        try:
            return DayState(**data)
        except (TypeError, KeyError) as exc:
            logging.error("State JSON ongeldig schema (%s): %s — leeg state aangemaakt.", f, exc)
            return DayState.empty(trade_date, start_capital)

    def save(self, state: DayState) -> None:
        with _STATE_LOCK:
            f = self._file(date.fromisoformat(state.trade_date))
            payload = json.dumps(asdict(state), indent=2)
            # Atomaire write: schrijf naar tmp dan replace → geen corrupt bestand bij crash
            fd, tmp = tempfile.mkstemp(dir=self.path, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as fp:
                    fp.write(payload)
                os.replace(tmp, f)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    def add_setup(self, state: DayState, setup: Setup) -> None:
        state.setups.append(asdict(setup))
        self.save(state)

    def set_setups(self, state: DayState, setups: List[Setup]) -> None:
        state.setups = [asdict(s) for s in setups]
        self.save(state)

    def open_position(self, state: DayState, pos: Position) -> None:
        state.positions[pos.ticker] = asdict(pos)
        self.save(state)

    def close_position(self, state: DayState, trade: ClosedTrade) -> None:
        state.positions.pop(trade.ticker, None)
        state.closed_trades.append(asdict(trade))
        self.save(state)

    def update_cash(self, state: DayState, cash: float) -> None:
        state.cash = round(cash, 2)
        self.save(state)
