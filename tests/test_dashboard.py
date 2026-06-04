from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from papertrader.config import validate_settings
from papertrader.risk_metrics import enrich_completed_trade, enrich_ongoing_position
from tests.conftest import make_settings


def test_enrich_ongoing_position_with_active_stop() -> None:
    row = enrich_ongoing_position(
        symbol="BTC/USD",
        quantity=1.0,
        entry_price=100.0,
        stop_price=95.0,
        entry_timestamp=1,
        total_equity=200.0,
        mark_price=102.0,
    )
    assert row["stop_active"] is True
    assert row["stop_status"] == "Active"
    assert row["risk_usd"] == 5.0
    assert row["risk_pct_of_equity"] == 2.5
    assert row["unrealized_pnl_usd"] == 2.0


def test_enrich_ongoing_position_without_stop_uses_full_position_risk() -> None:
    row = enrich_ongoing_position(
        symbol="CC/USD",
        quantity=300.0,
        entry_price=0.165543,
        stop_price=0.0,
        entry_timestamp=1,
        total_equity=50.0,
        mark_price=0.17,
    )
    assert row["stop_active"] is False
    assert row["stop_status"] == "Inactive"
    assert row["risk_usd"] == pytest.approx(51.0)
    assert row["risk_pct_of_equity"] == pytest.approx(102.0)


def test_enrich_completed_trade_legacy_exit() -> None:
    row = enrich_completed_trade({"symbol": "BTC/USD", "price": 105.0, "pnl": 4.5, "reason": "RSI_EXIT"})
    assert row["entry_price"] is None
    assert row["stop_price"] is None
    assert row["exit_price"] == 105.0
    assert row["pnl"] == 4.5
    assert "Profit/Loss" in row["pnl_label"]


def test_enrich_completed_trade_full_exit() -> None:
    row = enrich_completed_trade(
        {
            "symbol": "BTC/USD",
            "entry_price": 100.0,
            "stop_price": 95.0,
            "exit_price": 108.0,
            "pnl": 7.5,
            "reason": "RSI_EXIT",
        }
    )
    assert row["entry_price"] == 100.0
    assert row["stop_price"] == 95.0
    assert row["exit_price"] == 108.0


def test_dashboard_api_enriched_positions(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_path = state_dir / "paper_state.json"
    state_path.write_text(
        json.dumps(
            {
                "cash_usd": 10.0,
                "positions": {
                    "BTC/USD": {
                        "quantity": 1.0,
                        "entry_price": 100.0,
                        "entry_timestamp": 123,
                        "stop_price": 95.0,
                    }
                },
                "cooldown_remaining": 0,
                "day_key": "2026-05-25",
                "day_start_equity": 110.0,
            }
        )
    )
    trades_path = state_dir / "trades.jsonl"
    trades_path.write_text(
        json.dumps(
            {
                "type": "EXIT",
                "symbol": "ETH/USD",
                "entry_price": 50.0,
                "stop_price": 48.0,
                "exit_price": 55.0,
                "pnl": 4.2,
                "reason": "RSI_EXIT",
            }
        )
        + "\n"
    )

    settings = make_settings(state_dir, start_capital_usd=10.0)
    monkeypatch.setattr("papertrader.dashboard.settings", settings)
    monkeypatch.setattr("papertrader.dashboard.state_dir", state_dir)
    monkeypatch.setattr("papertrader.dashboard.state_path", state_path)
    monkeypatch.setattr("papertrader.dashboard.trades_path", trades_path)
    monkeypatch.setattr(
        "papertrader.dashboard.exchange.fetch_last_prices",
        lambda symbols: {symbol: 102.0 for symbol in symbols},
    )
    monkeypatch.setattr(
        "papertrader.dashboard._estimate_potential",
        lambda **kwargs: {"portfolio_state": "unknown", "portfolio_score": 0.0, "candidates": []},
    )

    from papertrader.dashboard import app

    client = TestClient(app)
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    payload = response.json()

    ongoing = payload["ongoing_positions"][0]
    assert ongoing["stop_active"] is True
    assert ongoing["risk_usd"] == 5.0

    completed = payload["completed_trades"][0]
    assert completed["entry_price"] == 50.0
    assert completed["stop_price"] == 48.0
    assert completed["exit_price"] == 55.0


def test_validate_settings_live_requires_keys(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, mode="live", live_trading_enabled=True)
    with pytest.raises(RuntimeError, match="KRAKEN_API_KEY"):
        validate_settings(settings)

    settings = make_settings(
        tmp_path,
        mode="live",
        live_trading_enabled=True,
        kraken_api_key="key",
        kraken_api_secret="secret",
    )
    validate_settings(settings)
