"""Tests voor quote-status (dashboard + trader, zelfde logica)."""
from __future__ import annotations

from stocktrader.config import Settings
from unittest.mock import patch

from stocktrader.market_snapshot import (
    apply_follow_status,
    build_quote_row,
    enrich_quotes_with_reference,
    placeholder_snapshots,
    quote_source_hint,
    quote_status,
    reference_price,
)
from stocktrader.parser import Setup


def _setup() -> Setup:
    return Setup(ticker="STI", hold=10.0, break_=28.0, t1=35.0, t2=40.0)


def _settings(**kwargs) -> Settings:
    base = dict(
        paper_capital=1000.0,
        data_source="finazon",
        polygon_api_key="",
        bar_poll_seconds=60,
        alpaca_api_key="",
        alpaca_api_secret="",
        alpaca_data_feed="iex",
        finazon_api_key="k",
        finazon_frequency="10s",
        broker="t212",
        t212_api_key="k",
        t212_api_secret="",
        t212_demo=True,
        t212_extended_hours=True,
        fx_eur_usd=1.08,
        fx_gbp_usd=1.27,
        fx_buffer_pct=0.03,
        t212_fx_fee_pct=0.15,
        max_order_usd=500.0,
        max_shares_per_order=0,
        volume_mult=2.0,
        orb_minutes=3,
        trailing_stop_enabled=True,
        trail_mode="trail",
        trail_activation_pct=5.0,
        trail_distance_pct=3.0,
        trail_steps="5:0,10:5,15:10",
        cash_reserve_pct=0.02,
        risk_threshold_usd=200.0,
        risk_per_trade_pct=0.02,
        max_position_pct=0.25,
        max_position_pct_large=0.10,
        large_cap_threshold=10000.0,
        max_positions=3,
        telegram_enabled=False,
        telegram_token="",
        telegram_chat_id="",
        dashboard_port=5001,
        state_dir="./state",
        log_level="INFO",
    )
    base.update(kwargs)
    return Settings(**base)


def test_quote_status_orb_phase():
    s = _setup()
    cfg = _settings()
    assert quote_status(
        s, cfg, high=30, close=29, volume=1000,
        orb_avg=None, orb_high=None, bar_num=2,
    ) == "ORB 2/3"


def test_quote_status_breakout_ok():
    s = _setup()
    cfg = _settings()
    assert quote_status(
        s, cfg, high=46, close=45, volume=5000,
        orb_avg=1000, orb_high=40, bar_num=5,
    ) == "breakout OK"


def test_quote_status_break_vol_low():
    s = _setup()
    cfg = _settings()
    assert quote_status(
        s, cfg, high=46, close=45, volume=500,
        orb_avg=1000, orb_high=40, bar_num=5,
    ) == "break, vol laag"


def test_quote_status_under_orb_high():
    s = _setup()
    cfg = _settings()
    assert quote_status(
        s, cfg, high=46, close=45, volume=5000,
        orb_avg=1000, orb_high=50, bar_num=5,
    ) == "onder ORB high"


def test_build_quote_row_blocked():
    row = build_quote_row(
        _setup(), _settings(),
        close=None, high=None, volume=None,
        orb_avg=None, orb_high=None, bar_num=0, blocked=True,
    )
    assert row["status"] == "geen data"
    assert row["last"] is None


def test_placeholder_snapshots():
    rows = placeholder_snapshots([_setup()])
    assert rows[0]["status"] == "start bot"
    assert rows[0]["ticker"] == "STI"


def test_quote_source_hint_finazon_live():
    hint = quote_source_hint("finazon", engine_live=True)
    assert "finazon" in hint
    assert "zelfde bron" in hint


def test_quote_source_hint_finazon_idle():
    hint = quote_source_hint("finazon", engine_live=False)
    assert "Start de bot" in hint


def test_apply_follow_status_marks_excluded():
    rows = placeholder_snapshots([_setup()])
    out = apply_follow_status(rows, {
        "STI": {"followed": False, "exclude_reason": "Geen Finazon-data"},
    })
    assert out[0]["followed"] is False
    assert out[0]["status"] == "Geen Finazon-data"


def test_enrich_quotes_with_reference():
    rows = placeholder_snapshots([_setup()])
    with patch(
        "stocktrader.market_snapshot.reference_price",
        return_value=(12.34, "vorige slot"),
    ):
        out = enrich_quotes_with_reference(rows, fetch_missing=True)
    assert out[0]["last"] == 12.34
    assert out[0]["last_label"] == "vorige slot"
    assert out[0]["last_source"] == "ref"


def test_reference_price_yahoo_parsing():
    payload = {
        "chart": {
            "result": [{
                "meta": {
                    "marketState": "PRE",
                    "preMarketPrice": 5.5,
                    "previousClose": 5.0,
                },
            }],
        },
    }
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = mock_urlopen.return_value.__enter__.return_value
        mock_resp.read.return_value = __import__("json").dumps(payload).encode()
        price, label = reference_price("STI")
    assert price == 5.5
    assert label == "pre-market"
