"""
Tests voor AlpacaBarStream — gemockte WebSocket, geen echte verbinding.
"""
from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from stocktrader.alpaca_stream import AlpacaBarStream


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stream(feed: str = "iex") -> AlpacaBarStream:
    return AlpacaBarStream(api_key="test_key", api_secret="test_secret", feed=feed)


# ---------------------------------------------------------------------------
# Constructor / validatie
# ---------------------------------------------------------------------------

def test_init_raises_without_key():
    with pytest.raises(RuntimeError, match="ALPACA_API_KEY"):
        AlpacaBarStream(api_key="", api_secret="secret")


def test_init_raises_without_secret():
    with pytest.raises(RuntimeError, match="ALPACA_API_KEY"):
        AlpacaBarStream(api_key="key", api_secret="")


def test_init_ok():
    s = _make_stream()
    assert s._feed == "iex"
    assert s._authenticated is False


def test_init_sip_feed():
    s = AlpacaBarStream(api_key="k", api_secret="s", feed="SIP")
    assert s._feed == "sip"


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
# Protocol-berichten: _handle_msg
# ---------------------------------------------------------------------------

def test_handle_connected_sends_auth():
    s = _make_stream()
    ws = MagicMock()
    s._handle_msg(ws, {"T": "success", "msg": "connected"})
    ws.send.assert_called_once()
    payload = json.loads(ws.send.call_args[0][0])
    assert payload["action"] == "auth"
    assert payload["key"] == "test_key"
    assert payload["secret"] == "test_secret"


def test_handle_authenticated_sends_subscribe():
    s = _make_stream()
    s._callbacks = {"AAPL": MagicMock(), "TSLA": MagicMock()}
    ws = MagicMock()
    s._handle_msg(ws, {"T": "success", "msg": "authenticated"})
    assert s._authenticated is True
    ws.send.assert_called_once()
    payload = json.loads(ws.send.call_args[0][0])
    assert payload["action"] == "subscribe"
    assert set(payload["bars"]) == {"AAPL", "TSLA"}


def test_handle_auth_error_stops_stream():
    s = _make_stream()
    s._running = True
    ws = MagicMock()
    s._handle_msg(ws, {"T": "error", "code": 402, "msg": "auth failed"})
    assert s._running is False
    ws.close.assert_called_once()


def test_handle_error_non_auth_does_not_stop():
    s = _make_stream()
    s._running = True
    ws = MagicMock()
    s._handle_msg(ws, {"T": "error", "code": 500, "msg": "server error"})
    assert s._running is True


# ---------------------------------------------------------------------------
# Bar emit
# ---------------------------------------------------------------------------

def test_emit_bar_calls_handler():
    s = _make_stream()
    received = []
    s._callbacks["AAPL"] = lambda *args: received.append(args)

    bar_msg = {
        "T": "b",
        "S": "AAPL",
        "o": 150.0,
        "h": 151.5,
        "l": 149.0,
        "c": 151.0,
        "v": 5000,
        "t": "2024-01-15T14:30:00Z",
    }
    s._emit_bar(bar_msg)

    assert len(received) == 1
    ticker, o, h, l, c, v, is_new = received[0]
    assert ticker == "AAPL"
    assert o == 150.0
    assert h == 151.5
    assert l == 149.0
    assert c == 151.0
    assert v == 5000
    assert is_new is True


def test_emit_bar_unknown_ticker_ignored():
    s = _make_stream()
    s._callbacks["AAPL"] = MagicMock()
    s._emit_bar({"T": "b", "S": "MSFT", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1})
    s._callbacks["AAPL"].assert_not_called()


def test_emit_bar_handler_exception_does_not_crash():
    s = _make_stream()

    def bad_handler(*args):
        raise RuntimeError("handler crash")

    s._callbacks["AAPL"] = bad_handler
    bar_msg = {"T": "b", "S": "AAPL", "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 100}
    s._emit_bar(bar_msg)  # mag niet opblazen


# ---------------------------------------------------------------------------
# on_message — JSON parsing
# ---------------------------------------------------------------------------

def test_on_message_list_payload():
    s = _make_stream()
    received = []
    s._callbacks["AAPL"] = lambda *a: received.append(a)
    ws = MagicMock()
    raw = json.dumps([
        {"T": "b", "S": "AAPL", "o": 10.0, "h": 11.0, "l": 9.5, "c": 10.5, "v": 200}
    ])
    s._on_message(ws, raw)
    assert len(received) == 1


def test_on_message_invalid_json_ignored():
    s = _make_stream()
    ws = MagicMock()
    s._on_message(ws, "not-json")  # mag niet crashen


# ---------------------------------------------------------------------------
# stop_stream zet _running op False
# ---------------------------------------------------------------------------

def test_stop_stream_clears_running():
    s = _make_stream()
    s._running = True
    ws_mock = MagicMock()
    s._ws = ws_mock
    s.stop_stream()
    assert s._running is False
    ws_mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# start_stream guard: dubbele start
# ---------------------------------------------------------------------------

def test_start_stream_no_double_start():
    s = _make_stream()
    s._running = True  # simuleer al lopend
    with patch("threading.Thread") as mock_thread:
        s.start_stream()
        mock_thread.assert_not_called()
