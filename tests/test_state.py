from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

from stocktrader.parser import Setup
from stocktrader.state import DayState, StateStore, trading_date


def test_trading_date_returns_date() -> None:
    d = trading_date()
    assert isinstance(d, date)


def test_state_store_load_save_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = StateStore(tmp)
        trade_date = date(2026, 6, 4)
        state = DayState.empty(trade_date, start_capital=100.0)
        state.active = True
        store.set_setups(state, [Setup("XOS", 6.30, 7.00, 8.00, 10.00)])

        loaded = store.load(trade_date, start_capital=0.0)
        assert loaded.active is True
        assert len(loaded.get_setups()) == 1
        assert loaded.get_setups()[0].ticker == "XOS"
        assert loaded.cash == 100.0


def test_state_store_corrupt_json_returns_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = StateStore(tmp)
        trade_date = date(2026, 6, 6)
        path = Path(tmp) / f"{trade_date.isoformat()}.json"
        path.write_text("{not valid json", encoding="utf-8")
        loaded = store.load(trade_date, start_capital=50.0)
        assert loaded.cash == 50.0
        assert loaded.active is False
        assert loaded.crashed is False


def test_state_store_atomic_write() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = StateStore(tmp)
        trade_date = date(2026, 6, 5)
        state = DayState.empty(trade_date, start_capital=50.0)
        store.save(state)

        path = Path(tmp) / f"{trade_date.isoformat()}.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["trade_date"] == "2026-06-05"
        assert data["cash"] == 50.0
        assert not list(Path(tmp).glob("*.tmp"))
