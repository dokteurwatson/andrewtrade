"""
Tests voor T212Client — alle HTTP-calls gemockt, geen echte verbinding.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from stocktrader.t212_client import T212Client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(demo: bool = True) -> T212Client:
    return T212Client(api_key="test_key", api_secret="test_secret", demo=demo)


def _mock_get(client: T212Client, return_value):
    """Patch _get om een vaste waarde terug te geven."""
    client._get = MagicMock(return_value=return_value)


def _mock_post(client: T212Client, return_value: dict):
    client._post = MagicMock(return_value=return_value)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

def test_init_raises_without_key():
    with pytest.raises(RuntimeError, match="T212_API_KEY"):
        T212Client(api_key="")


def test_init_demo_base_url():
    c = T212Client(api_key="k", demo=True)
    assert "demo" in c._base


def test_init_live_base_url():
    c = T212Client(api_key="k", demo=False)
    assert "live" in c._base


# ---------------------------------------------------------------------------
# _load_instruments / is_tradable / _map_ticker
# ---------------------------------------------------------------------------

_INSTRUMENTS = [
    {"ticker": "AAPL_US_EQ", "shortName": "AAPL", "type": "STOCK"},
    {"ticker": "TSLA_US_EQ", "shortName": "TSLA", "type": "STOCK"},
    {"ticker": "MSFT_US_EQ", "shortName": "MSFT", "type": "STOCK"},
    # Zelfde shortName, andere markt — US_EQ moet gewonnen worden
    {"ticker": "AAPL_EQ",    "shortName": "AAPL", "type": "STOCK"},
]


def _connected_client() -> T212Client:
    c = _make_client()
    _mock_get(c, _INSTRUMENTS)
    c.connect()
    return c


def test_load_instruments_builds_map():
    c = _connected_client()
    assert c._instrument_map["AAPL"] == "AAPL_US_EQ"
    assert c._instrument_map["TSLA"] == "TSLA_US_EQ"


def test_us_eq_preferred_over_other_market():
    c = _connected_client()
    assert c._instrument_map["AAPL"] == "AAPL_US_EQ"


def test_is_tradable_known_ticker():
    c = _connected_client()
    assert c.is_tradable("AAPL") is True
    assert c.is_tradable("aapl") is True  # case-insensitive


def test_is_tradable_unknown_ticker():
    c = _connected_client()
    assert c.is_tradable("XYZ") is False


def test_map_ticker_known():
    c = _connected_client()
    assert c._map_ticker("AAPL") == "AAPL_US_EQ"


def test_map_ticker_unknown_raises():
    c = _connected_client()
    with pytest.raises(ValueError, match="UNKNOWN"):
        c._map_ticker("UNKNOWN")


# ---------------------------------------------------------------------------
# get_cash
# ---------------------------------------------------------------------------

def test_get_cash_free_field():
    c = _connected_client()
    c._get = MagicMock(return_value={"cash": {"free": 1234.56}})
    assert c.get_cash() == pytest.approx(1234.56)


def test_get_cash_availableToTrade_fallback():
    c = _connected_client()
    c._get = MagicMock(return_value={"cash": {"availableToTrade": 999.0}})
    assert c.get_cash() == pytest.approx(999.0)


def test_get_cash_returns_zero_on_error():
    c = _connected_client()
    c._get = MagicMock(side_effect=RuntimeError("network error"))
    assert c.get_cash() == 0.0


# ---------------------------------------------------------------------------
# price cache
# ---------------------------------------------------------------------------

def test_update_last_price_and_get():
    c = _connected_client()
    c.update_last_price("AAPL", 175.50)
    assert c.get_latest_price("AAPL") == pytest.approx(175.50)


def test_get_latest_price_unknown_ticker_returns_none():
    c = _connected_client()
    c._get = MagicMock(side_effect=ValueError("not found"))
    result = c.get_latest_price("UNKNOWN")
    assert result is None


# ---------------------------------------------------------------------------
# buy_market / sell_market
# ---------------------------------------------------------------------------

def test_buy_market_returns_order_id():
    c = _connected_client()
    _mock_post(c, {"id": "order-123", "status": "PENDING"})
    order_id = c.buy_market("AAPL", 10)
    assert order_id == "order-123"
    c._post.assert_called_once()
    call_args = c._post.call_args
    assert call_args[0][0] == "/equity/orders/market"
    payload = call_args[0][1]
    assert payload["ticker"] == "AAPL_US_EQ"
    assert payload["quantity"] == 10
    assert payload["type"] == "MARKET"
    assert payload["timeValidity"] == "DAY"


def test_sell_market_returns_order_id():
    c = _connected_client()
    _mock_post(c, {"id": "order-456"})
    order_id = c.sell_market("TSLA", 5)
    assert order_id == "order-456"
    payload = c._post.call_args[0][1]
    assert payload["ticker"] == "TSLA_US_EQ"
    assert payload["quantity"] == -5  # T212: negatief = verkoop


def test_buy_market_unknown_ticker_raises():
    c = _connected_client()
    with pytest.raises(ValueError, match="UNKNOWN"):
        c.buy_market("UNKNOWN", 1)


def test_sell_market_http_error_raises():
    c = _connected_client()
    c._post = MagicMock(side_effect=RuntimeError("T212 POST → HTTP 400: insufficient funds"))
    with pytest.raises(RuntimeError, match="HTTP 400"):
        c.sell_market("AAPL", 100)


# ---------------------------------------------------------------------------
# close_all_positions
# ---------------------------------------------------------------------------

def test_close_all_positions_sells_each():
    c = _connected_client()
    positions = [
        {"ticker": "AAPL_US_EQ", "quantity": 10},
        {"ticker": "TSLA_US_EQ", "quantity": 5},
    ]
    c._get = MagicMock(return_value=positions)
    c._post = MagicMock(return_value={"id": "eod-order"})
    c.close_all_positions()
    assert c._post.call_count == 2


def test_close_all_positions_empty():
    c = _connected_client()
    c._get = MagicMock(return_value=[])
    c._post = MagicMock()
    c.close_all_positions()
    c._post.assert_not_called()


def test_close_all_positions_get_error_does_not_crash():
    c = _connected_client()
    c._get = MagicMock(side_effect=RuntimeError("network error"))
    c.close_all_positions()  # mag niet opblazen


# ---------------------------------------------------------------------------
# bind_state — no-op
# ---------------------------------------------------------------------------

def test_bind_state_is_noop():
    c = _connected_client()
    c.bind_state(MagicMock(), MagicMock())  # mag niet crashen


# ---------------------------------------------------------------------------
# Demo vs Live mode label
# ---------------------------------------------------------------------------

def test_mode_label_demo():
    c = T212Client(api_key="k", demo=True)
    assert c._mode == "DEMO"


def test_mode_label_live():
    c = T212Client(api_key="k", demo=False)
    assert c._mode == "LIVE"


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------

def test_auth_header_basic_when_secret_provided():
    import base64
    c = T212Client(api_key="mykey", api_secret="mysecret")
    header = c._auth_header()
    assert header.startswith("Basic ")
    decoded = base64.b64decode(header[6:]).decode()
    assert decoded == "mykey:mysecret"


def test_auth_header_legacy_when_no_secret():
    c = T212Client(api_key="mykey", api_secret="")
    header = c._auth_header()
    assert header == "mykey"


def test_headers_dict_contains_auth():
    c = T212Client(api_key="k", api_secret="s")
    headers = c._headers()
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Basic ")
    assert headers["Content-Type"] == "application/json"
