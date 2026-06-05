"""
Tests voor T212Client — alle HTTP-calls gemockt, geen echte verbinding.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch  # noqa: F401 — patch used in test_cash_in_usd

import pytest

from stocktrader.t212_client import (
    T212AuthError,
    T212Client,
    T212CloseOnlyError,
    T212NetworkError,
    T212PositionNotFoundError,
    T212RateLimitError,
)


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
    c._get = MagicMock(return_value={"currency": "EUR", "cash": {"free": 1234.56}})
    assert c.get_cash() == pytest.approx(1234.56)
    assert c.get_account_currency() == "EUR"


def test_get_cash_availableToTrade_fallback():
    c = _connected_client()
    c._get = MagicMock(return_value={"cash": {"availableToTrade": 999.0}})
    assert c.get_cash() == pytest.approx(999.0)


def test_get_cash_raises_on_auth_error():
    c = _connected_client()
    c._get = MagicMock(side_effect=T212AuthError("HTTP 401"))
    with pytest.raises(T212AuthError):
        c.get_cash()


def test_get_cash_raises_on_network_error():
    c = _connected_client()
    c._get = MagicMock(side_effect=T212NetworkError("timeout"))
    with pytest.raises(T212NetworkError):
        c.get_cash()


def test_cash_in_usd_eur_account():
    from stocktrader.t212_client import T212AccountInfo
    c = T212Client(api_key="k", fx_eur_usd=1.10, fx_buffer_pct=0.0)
    c._account_cache = T212AccountInfo(cash=100.0, currency="EUR")
    with patch("stocktrader.fx_rates.get_rate_to_usd", return_value=1.10):
        assert c.cash_in_usd(100.0) == pytest.approx(110.0)


def test_get_cash_uses_cache_within_ttl():
    c = _connected_client()
    mock_get = MagicMock(return_value={"currency": "USD", "cash": {"free": 500.0}})
    c._get = mock_get
    assert c.get_cash() == pytest.approx(500.0)
    mock_get.return_value = {"cash": {"free": 999.0}}
    assert c.get_cash() == pytest.approx(500.0)
    assert mock_get.call_count == 1


def test_get_cash_force_bypasses_cache():
    c = _connected_client()
    c._get = MagicMock(return_value={"cash": {"free": 500.0}})
    c.get_cash()
    c._get = MagicMock(return_value={"cash": {"free": 999.0}})
    assert c.get_cash(force=True) == pytest.approx(999.0)


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

def test_buy_market_no_extended_hours_when_disabled():
    c = T212Client(api_key="k", extended_hours=False)
    c._connected = True
    c._instrument_map = {"AAPL": "AAPL_US_EQ"}
    _mock_post(c, {"id": "order-1"})
    c.buy_market("AAPL", 1)
    payload = c._post.call_args[0][1]
    assert "extendedHours" not in payload


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
    assert payload["extendedHours"] is True
    assert "type" not in payload
    assert "timeValidity" not in payload


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


def test_sell_market_position_not_found_raises():
    c = _connected_client()
    c._post = MagicMock(
        side_effect=T212PositionNotFoundError("HTTP 400: no position found")
    )
    with pytest.raises(T212PositionNotFoundError):
        c.sell_market("AAPL", 100)


def test_sell_market_http_error_raises():
    c = _connected_client()
    from stocktrader.t212_client import T212Error
    c._post = MagicMock(side_effect=T212Error("T212 POST → HTTP 400: insufficient funds"))
    with pytest.raises(T212Error, match="HTTP 400"):
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
    c._get = MagicMock(side_effect=T212NetworkError("network error"))
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


# ---------------------------------------------------------------------------
# Rate limit retry
# ---------------------------------------------------------------------------

def test_classify_http_error_429():
    import urllib.error
    c = _make_client()
    exc = urllib.error.HTTPError(
        url="http://test", code=429, msg="Too Many", hdrs={}, fp=None
    )
    err = c._classify_http_error(exc, "/test", "rate limited")
    assert isinstance(err, T212RateLimitError)


def test_classify_http_error_401():
    import urllib.error
    c = _make_client()
    exc = urllib.error.HTTPError(
        url="http://test", code=401, msg="Unauthorized", hdrs={}, fp=None
    )
    err = c._classify_http_error(exc, "/test", "unauthorized")
    assert isinstance(err, T212AuthError)


def test_classify_http_error_close_only():
    import urllib.error
    c = _make_client()
    exc = urllib.error.HTTPError(
        url="http://test", code=400, msg="Bad Request", hdrs={}, fp=None
    )
    body = (
        '{"type":"/api-errors/instrument-close-only-mode",'
        '"detail":"Close only mode"}'
    )
    err = c._classify_http_error(exc, "/equity/orders/market", body)
    assert isinstance(err, T212CloseOnlyError)
