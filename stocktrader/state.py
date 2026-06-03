"""
Dagelijkse state — watchlist, posities, trades.
Persisteert naar JSON zodat een herstart geen data verliest.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from .parser import Setup


@dataclass
class Position:
    ticker:      str
    shares:      int
    entry_price: float
    stop_price:  float
    target_price: float
    entry_time:  str
    order_id:    str


@dataclass
class ClosedTrade:
    ticker:      str
    shares:      int
    entry_price: float
    exit_price:  float
    entry_time:  str
    exit_time:   str
    reason:      str   # "T1", "STOP", "EOD", "MANUAL"
    pnl:         float


@dataclass
class DayState:
    trade_date:   str
    setups:       List[dict]
    positions:    Dict[str, dict]
    closed_trades: List[dict]
    active:       bool
    cash:         float = 0.0   # huidig cash saldo (gepersisteerd)

    @staticmethod
    def empty(trade_date: date, start_capital: float = 0.0) -> "DayState":
        return DayState(
            trade_date=trade_date.isoformat(),
            setups=[],
            positions={},
            closed_trades=[],
            active=False,
            cash=start_capital,
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
            ticker: Position(**pos)
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

    def load(self, trade_date: date, start_capital: float = 0.0) -> DayState:
        f = self._file(trade_date)
        if not f.exists():
            return DayState.empty(trade_date, start_capital)
        with open(f) as fp:
            data = json.load(fp)
        # backwards compat: oude state zonder cash veld
        if "cash" not in data:
            data["cash"] = start_capital
        return DayState(**data)

    def save(self, state: DayState) -> None:
        f = self._file(date.fromisoformat(state.trade_date))
        with open(f, "w") as fp:
            json.dump(asdict(state), fp, indent=2)

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
