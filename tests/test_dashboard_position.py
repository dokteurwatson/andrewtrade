"""Tests voor dashboard stop-update route."""
from __future__ import annotations

import pytest

import stocktrader.dashboard as dashboard
from stocktrader.state import DayState, StateStore, trading_date


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "store", StateStore(str(tmp_path)))
    dashboard.trader._state = None
    dashboard.trader._engine_live = False
    dashboard.trader._running = False
    return dashboard.app.test_client()


def _seed_position(
    ticker: str = "LASE",
    stop: float = 2.80,
    target: float = 4.20,
) -> DayState:
    state = DayState(
        trade_date=trading_date().isoformat(),
        cash=50.0,
        setups=[],
        positions={
            ticker: {
                "ticker": ticker,
                "shares": 16,
                "entry_price": 3.41,
                "stop_price": stop,
                "target_price": target,
                "entry_time": "09:37",
                "order_id": "test-1",
                "t2_price": 6.00,
            }
        },
        closed_trades=[],
        active=False,
    )
    dashboard.store.save(state)
    dashboard.trader._state = state
    return state


def test_update_stop_success(client):
    _seed_position()
    resp = client.post("/position/LASE/update", data={"hold": "3.30"}, follow_redirects=False)
    assert resp.status_code == 302
    reloaded = dashboard.store.load_date(trading_date(), 50.0)
    assert reloaded is not None
    assert reloaded.positions["LASE"]["stop_price"] == 3.30


def test_update_stop_live_engine_uses_memory(client, monkeypatch):
    state = _seed_position()
    monkeypatch.setattr(dashboard.trader, "is_engine_live", lambda: True)
    resp = client.post("/position/LASE/update", data={"hold": "3.30"}, follow_redirects=False)
    assert resp.status_code == 302
    assert state.positions["LASE"]["stop_price"] == 3.30


def test_update_stop_rejects_above_target(client):
    _seed_position()
    resp = client.post("/position/LASE/update", data={"hold": "4.50"}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"moet onder T1" in resp.data


def test_update_stop_unknown_ticker(client):
    _seed_position()
    resp = client.post("/position/FAKE/update", data={"hold": "3.00"}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Geen open positie" in resp.data
