"""Tests voor setup toggle en update routes."""
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


def _seed_setups(*, enabled: bool = True) -> DayState:
    state = DayState(
        trade_date=trading_date().isoformat(),
        cash=50.0,
        setups=[
            {
                "ticker": "LASE",
                "hold": 2.80,
                "break_": 3.20,
                "t1": 4.20,
                "t2": 6.00,
                "enabled": enabled,
            }
        ],
        positions={},
        closed_trades=[],
        active=False,
    )
    dashboard.store.save(state)
    dashboard.trader._state = state
    return state


def test_toggle_setup_disables(client):
    _seed_setups()
    resp = client.post("/setup/LASE/toggle", follow_redirects=False)
    assert resp.status_code == 302
    reloaded = dashboard.store.load_date(trading_date(), 50.0)
    assert reloaded is not None
    assert reloaded.setups[0]["enabled"] is False


def test_update_setup_t1_t2(client):
    _seed_setups()
    resp = client.post(
        "/setup/LASE/update",
        data={"hold": "2.80", "break_": "3.20", "t1": "4.50", "t2": "6.50"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    reloaded = dashboard.store.load_date(trading_date(), 50.0)
    assert reloaded is not None
    s = reloaded.setups[0]
    assert s["t1"] == 4.50
    assert s["t2"] == 6.50


def test_update_setup_rejects_stop_above_new_t1(client):
    """Bug-regressie: setup mag niet gemuteerd worden als validatie faalt."""
    state = _seed_setups()
    state.positions["LASE"] = {
        "ticker": "LASE",
        "shares": 10,
        "entry_price": 3.41,
        "stop_price": 4.10,   # stop al boven entry (trailing heeft opgetrokken)
        "target_price": 4.20,
        "entry_time": "09:37",
        "order_id": "test-1",
        "t2_price": 6.00,
    }
    dashboard.store.save(state)

    # Probeer T1 te zakken tot 4.00 — stop 4.10 > nieuwe T1 4.00, moet geweigerd worden
    resp = client.post(
        "/setup/LASE/update",
        data={"hold": "2.80", "break_": "3.20", "t1": "4.00", "t2": "6.00"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"moet onder nieuwe T1" in resp.data

    # Kritiek: setup mag NIET gemuteerd zijn
    reloaded = dashboard.store.load_date(trading_date(), 50.0)
    assert reloaded is not None
    assert reloaded.setups[0]["t1"] == 4.20   # ongewijzigd
    assert reloaded.positions["LASE"]["target_price"] == 4.20   # ongewijzigd


def test_update_setup_rejects_stop_above_new_t1_live_engine(client, monkeypatch):
    """Bug-regressie: in-memory state niet dirty bij afwijzing terwijl engine live is."""
    state = _seed_setups()
    state.positions["LASE"] = {
        "ticker": "LASE",
        "shares": 10,
        "entry_price": 3.41,
        "stop_price": 4.10,
        "target_price": 4.20,
        "entry_time": "09:37",
        "order_id": "test-1",
        "t2_price": 6.00,
    }
    dashboard.store.save(state)
    monkeypatch.setattr(dashboard.trader, "is_engine_live", lambda: True)

    resp = client.post(
        "/setup/LASE/update",
        data={"hold": "2.80", "break_": "3.20", "t1": "4.00", "t2": "6.00"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"moet onder nieuwe T1" in resp.data

    # In-memory state (trader._state) mag ook niet gemuteerd zijn
    assert state.setups[0]["t1"] == 4.20
    assert state.positions["LASE"]["target_price"] == 4.20


def test_update_setup_syncs_open_position(client):
    state = _seed_setups()
    state.positions["LASE"] = {
        "ticker": "LASE",
        "shares": 10,
        "entry_price": 3.41,
        "stop_price": 2.80,
        "target_price": 4.20,
        "entry_time": "09:37",
        "order_id": "test-1",
        "t2_price": 6.00,
    }
    dashboard.store.save(state)
    resp = client.post(
        "/setup/LASE/update",
        data={"hold": "2.80", "break_": "3.20", "t1": "4.80", "t2": "7.00"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    reloaded = dashboard.store.load_date(trading_date(), 50.0)
    assert reloaded is not None
    assert reloaded.positions["LASE"]["target_price"] == 4.80
    assert reloaded.positions["LASE"]["t2_price"] == 7.00
