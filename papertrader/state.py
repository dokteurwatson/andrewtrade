from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


def utc_day_key(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class Position:
    symbol: str
    quantity: float
    entry_price: float
    entry_timestamp: int
    stop_price: float


@dataclass
class BotState:
    cash_usd: float
    positions: Dict[str, Position] = field(default_factory=dict)
    last_candle_ts: Dict[str, int] = field(default_factory=dict)
    consecutive_losses: int = 0
    cooldown_remaining: int = 0
    day_key: str = ""
    day_start_equity: float = 0.0


class StateStore:
    def __init__(self, state_dir: str, starting_cash: float) -> None:
        self._dir = Path(state_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "paper_state.json"
        self._starting_cash = starting_cash

    def load(self) -> BotState:
        if not self._path.exists():
            return BotState(cash_usd=self._starting_cash, day_start_equity=self._starting_cash)

        data = json.loads(self._path.read_text())
        positions = {
            symbol: Position(
                symbol=symbol,
                quantity=float(value["quantity"]),
                entry_price=float(value["entry_price"]),
                entry_timestamp=int(value["entry_timestamp"]),
                stop_price=float(value["stop_price"]),
            )
            for symbol, value in data.get("positions", {}).items()
        }
        return BotState(
            cash_usd=float(data.get("cash_usd", self._starting_cash)),
            positions=positions,
            last_candle_ts={k: int(v) for k, v in data.get("last_candle_ts", {}).items()},
            consecutive_losses=int(data.get("consecutive_losses", 0)),
            cooldown_remaining=int(data.get("cooldown_remaining", 0)),
            day_key=str(data.get("day_key", "")),
            day_start_equity=float(data.get("day_start_equity", self._starting_cash)),
        )

    def save(self, state: BotState) -> None:
        payload = {
            "cash_usd": state.cash_usd,
            "positions": {
                symbol: {
                    "quantity": pos.quantity,
                    "entry_price": pos.entry_price,
                    "entry_timestamp": pos.entry_timestamp,
                    "stop_price": pos.stop_price,
                }
                for symbol, pos in state.positions.items()
            },
            "last_candle_ts": state.last_candle_ts,
            "consecutive_losses": state.consecutive_losses,
            "cooldown_remaining": state.cooldown_remaining,
            "day_key": state.day_key,
            "day_start_equity": state.day_start_equity,
        }
        self._path.write_text(json.dumps(payload, indent=2))


def calculate_total_equity(cash_usd: float, positions: Dict[str, Position], last_prices: Dict[str, float]) -> float:
    total = cash_usd
    for symbol, position in positions.items():
        price = last_prices.get(symbol)
        if price is None:
            continue
        total += position.quantity * price
    return total
