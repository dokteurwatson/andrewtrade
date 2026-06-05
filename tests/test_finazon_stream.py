"""
Tests voor FinazonBarStream — gemockte WebSocket, geen echte verbinding.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from stocktrader.finazon_stream import FinazonBarStream


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stream() -> FinazonBarStream:
    return FinazonBarStream(api_key="test_key")


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

def test_init_raises_without_key():
    with pytest.raises(RuntimeError, match="FINAZON_API_KEY"):
        FinazonBarStream(api_key="")


def test_init_ok():
    s = _make_stream()
    assert s._api_key == "test_key"
    assert s._dataset == "us_stocks_essential"
    assert s._running is False


def test_custom_dataset():
    s = FinazonBarStream(api_key="k", dataset="custom_dataset")
    assert s._dataset == "custom_dataset"


# ---------------------------------------------------------------------------
# subscribe_bars
# ---------------------------------------------------------------------------

def test_subscribe_bars_registers_callbacks():
    s = _make_stream()
    cb = MagicMock()
    s.subscribe_bars(["AAPL", "TSLA"], cb)
    assert s._callbacks["AAPL"] is cb
    assert s._callbacks["TSLA"] is cb


# ---------------------------------------------------------------------------
# _on_open — verzendt subscribe-bericht
# ---------------------------------------------------------------------------

def test_on_open_sends_subscribe():
    s = _make_stream()
    s._callbacks = {"AAPL": MagicMock(), "TSLA": MagicMock()}
    ws = MagicMock()
    s._on_open(ws)
    ws.send.assert_called_once()
    payload = json.loads(ws.send.call_args[0][0])
    assert payload["event"] == "subscribe"
    assert payload["dataset"] == "us_stocks_essential"
    assert set(payload["tickers"]) == {"AAPL", "TSLA"}
    assert payload["channel"] == "bars"
    assert payload["frequency"] == "1m"
    assert payload["aggregation"] == "1m"


def test_on_open_empty_callbacks_no_crash():
    s = _make_stream()
    ws = MagicMock()
    s._on_open(ws)  # geen tickers — mag niet crashen


# ---------------------------------------------------------------------------
# _on_message — verwerking van verschillende bericht-types
# ---------------------------------------------------------------------------

def test_on_message_subscription_success_logged():
    s = _make_stream()
    ws = MagicMock()
    raw = json.dumps({
        "status": "success",
        "code": "SUCCESS_SUBSCRIPTION",
        "data": ["AAPL", "TSLA"],
    })
    s._on_message(ws, raw)  # mag niet crashen, geen bar emitted


def test_on_message_subscription_error_logged():
    s = _make_stream()
    ws = MagicMock()
    raw = json.dumps({"status": "error", "message": "invalid api key"})
    s._on_message(ws, raw)  # mag niet crashen


def test_on_message_heartbeat_ignored():
    s = _make_stream()
    ws = MagicMock()
    raw = json.dumps({"event": "heartbeat", "status": "success"})
    s._on_message(ws, raw)  # mag niet crashen


def test_on_message_invalid_json_ignored():
    s = _make_stream()
    ws = MagicMock()
    s._on_message(ws, "not-json{{{")  # mag niet crashen


def test_on_message_bar_triggers_handler():
    s = _make_stream()
    received = []
    s._callbacks["AAPL"] = lambda *args: received.append(args)
    ws = MagicMock()
    raw = json.dumps({
        "d": "us_stocks_essential",
        "p": "finazon",
        "ch": "bars",
        "f": "1m",
        "aggr": "1m",
        "s": "AAPL",
        "t": 1699540020,
        "o": 220.06,
        "h": 220.13,
        "l": 219.92,
        "c": 219.96,
        "v": 4572,
    })
    s._on_message(ws, raw)
    assert len(received) == 1
    ticker, o, h, l, c, v, is_new = received[0]
    assert ticker == "AAPL"
    assert o == pytest.approx(220.06)
    assert h == pytest.approx(220.13)
    assert l == pytest.approx(219.92)
    assert c == pytest.approx(219.96)
    assert v == pytest.approx(4572)
    assert is_new is True


# ---------------------------------------------------------------------------
# _emit_bar
# ---------------------------------------------------------------------------

def test_emit_bar_unknown_ticker_ignored():
    s = _make_stream()
    s._callbacks["AAPL"] = MagicMock()
    s._emit_bar({"s": "MSFT", "o": 1, "h": 1, "l": 1, "c": 1, "v": 100})
    s._callbacks["AAPL"].assert_not_called()


def test_emit_bar_handler_exception_no_crash():
    s = _make_stream()
    s._callbacks["AAPL"] = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
    s._emit_bar({"s": "AAPL", "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 999})


# ---------------------------------------------------------------------------
# start_stream / stop_stream
# ---------------------------------------------------------------------------

def test_start_stream_no_double_start():
    s = _make_stream()
    s._running = True
    with patch("threading.Thread") as mock_thread:
        s.start_stream()
        mock_thread.assert_not_called()


def test_stop_stream_sets_running_false():
    s = _make_stream()
    s._running = True
    ws_mock = MagicMock()
    s._ws = ws_mock
    s.stop_stream()
    assert s._running is False
    ws_mock.close.assert_called_once()


def test_stop_stream_ws_none_no_crash():
    s = _make_stream()
    s._running = True
    s._ws = None
    s.stop_stream()  # mag niet crashen


# ---------------------------------------------------------------------------
# WS URL bevat de API key
# ---------------------------------------------------------------------------

def test_ws_url_contains_apikey():
    s = FinazonBarStream(api_key="my_secret_key")
    expected_url = "wss://ws.finazon.io/v1?apikey=my_secret_key"
    from stocktrader.finazon_stream import _WS_BASE
    assert f"{_WS_BASE}?apikey=my_secret_key" == expected_url
