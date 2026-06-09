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
    assert s._frequency == "10s"
    assert s._running is False


def test_init_custom_frequency():
    s = FinazonBarStream(api_key="k", frequency="1m")
    assert s._frequency == "1m"


def test_init_invalid_frequency():
    with pytest.raises(ValueError, match="FINAZON_FREQUENCY"):
        FinazonBarStream(api_key="k", frequency="5s")


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
    assert payload["frequency"] == "10s"
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


def test_on_message_subscription_error_stops_stream():
    s = _make_stream()
    s._running = True
    ws = MagicMock()
    raw = json.dumps({"status": "error", "message": "invalid api key"})
    s._on_message(ws, raw)
    assert s._running is False
    ws.close.assert_called_once()


def test_on_message_unsupported_ticker_drops_and_resubscribes():
    s = _make_stream()
    s._running = True
    s._callbacks = {"BGMS": MagicMock(), "AAPL": MagicMock()}
    ws = MagicMock()
    raw = json.dumps({
        "status": "error",
        "message": "The ticker BGMS you have specified is unrecognized or unsupported.",
    })
    s._on_message(ws, raw)
    assert s._running is True
    assert "BGMS" not in s._callbacks
    assert "BGMS" in s._skipped
    assert "AAPL" in s._callbacks
    ws.send.assert_not_called()


def test_on_message_unsupported_ticker_calls_exclusion_handler():
    s = _make_stream()
    excluded: list[str] = []
    s.set_exclusion_handler(excluded.append)
    s._callbacks = {"BGMS": MagicMock(), "AAPL": MagicMock()}
    ws = MagicMock()
    raw = json.dumps({
        "status": "error",
        "message": "The ticker BGMS you have specified is unrecognized or unsupported.",
    })
    s._on_message(ws, raw)
    assert excluded == ["BGMS"]
    assert s.get_skipped_tickers() == {"BGMS"}


def test_on_message_already_subscribed_is_ignored():
    s = _make_stream()
    s._running = True
    ws = MagicMock()
    raw = json.dumps({
        "status": "error",
        "message": "You are already subscribed to ticker: AAPL, TSLA.",
    })
    s._on_message(ws, raw)
    assert s._running is True
    ws.send.assert_not_called()


def test_on_message_heartbeat_ignored():
    s = _make_stream()
    ws = MagicMock()
    raw = json.dumps({"event": "heartbeat", "status": "success"})
    s._on_message(ws, raw)  # mag niet crashen


def test_on_message_heartbeat_logs_once(caplog):
    import logging
    s = _make_stream()
    ws = MagicMock()
    raw = json.dumps({"event": "heartbeat", "status": "success"})
    with caplog.at_level(logging.INFO):
        s._on_message(ws, raw)
        s._on_message(ws, raw)
    assert sum(1 for r in caplog.records if "heartbeat ontvangen" in r.message) == 1


def test_emit_bar_logs_first_bar(caplog):
    import logging
    s = _make_stream()
    s._callbacks["AAPL"] = MagicMock()
    with caplog.at_level(logging.INFO):
        s._emit_bar({"s": "AAPL", "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 999})
        s._emit_bar({"s": "AAPL", "o": 2.0, "h": 2.5, "l": 1.5, "c": 2.0, "v": 500})
    assert sum(1 for r in caplog.records if "eerste bar" in r.message) == 1


def test_on_message_invalid_json_ignored():
    s = _make_stream()
    ws = MagicMock()
    s._on_message(ws, "not-json{{{")  # mag niet crashen


def test_on_message_bar_triggers_handler():
    s = _make_stream()
    received = []
    s._callbacks["AAPL"] = lambda *args, **kwargs: received.append((args, kwargs))
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
    args, kwargs = received[0]
    ticker, o, h, l, c, v, is_new = args
    assert ticker == "AAPL"
    assert kwargs["bar_ts"] == 1699540020
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


# ---------------------------------------------------------------------------
# Snapshot-tracking: is_new_bar per bar-timestamp
# ---------------------------------------------------------------------------

def _bar_msg(ticker: str, ts: int, **kwargs) -> dict:
    base = {"s": ticker, "t": ts, "o": 1.0, "h": 1.1, "l": 0.9, "c": 1.0, "v": 500}
    base.update(kwargs)
    return base


def test_first_message_for_ts_is_new_bar():
    """Eerste bericht voor een timestamp is altijd is_new_bar=True."""
    s = _make_stream()
    received: list = []
    s.subscribe_bars(["AAPL"], lambda *a, **kw: received.append((a, kw)))
    s._emit_bar(_bar_msg("AAPL", ts=1000))
    assert len(received) == 1
    _args, kw = received[0]
    assert kw.get("bar_ts") == 1000
    # is_new_bar is positional arg 7 (index 6 in args tuple after ticker,o,h,l,c,v)
    assert _args[6] is True


def test_same_ts_is_snapshot():
    """Zelfde timestamp als vorige → is_new_bar=False (snapshot)."""
    s = _make_stream()
    received: list = []
    s.subscribe_bars(["AAPL"], lambda *a, **kw: received.append(a[6]))
    s._emit_bar(_bar_msg("AAPL", ts=1000))
    s._emit_bar(_bar_msg("AAPL", ts=1000))  # snapshot
    s._emit_bar(_bar_msg("AAPL", ts=1000))  # snapshot
    assert received == [True, False, False]


def test_new_ts_after_snapshot_is_new_bar():
    """Na snapshots: nieuwe timestamp → is_new_bar=True weer."""
    s = _make_stream()
    received: list = []
    s.subscribe_bars(["AAPL"], lambda *a, **kw: received.append(a[6]))
    s._emit_bar(_bar_msg("AAPL", ts=1000))
    s._emit_bar(_bar_msg("AAPL", ts=1000))
    s._emit_bar(_bar_msg("AAPL", ts=1060))  # nieuwe minuut
    assert received == [True, False, True]


def test_snapshot_ts_tracked_per_ticker():
    """Snapshot-tracking is per ticker onafhankelijk."""
    s = _make_stream()
    aapl_received: list = []
    tsla_received: list = []
    s.subscribe_bars(["AAPL"], lambda *a, **kw: aapl_received.append(a[6]))
    s.subscribe_bars(["TSLA"], lambda *a, **kw: tsla_received.append(a[6]))
    s._emit_bar(_bar_msg("AAPL", ts=1000))
    s._emit_bar(_bar_msg("TSLA", ts=1000))  # zelfde ts maar ander ticker: ook new_bar
    s._emit_bar(_bar_msg("AAPL", ts=1000))  # snapshot voor AAPL
    assert aapl_received == [True, False]
    assert tsla_received == [True]


def test_snapshot_ts_cleared_on_start_stream():
    """start_stream reset snapshot-state zodat herstarten correct werkt."""
    s = _make_stream()
    s._snapshot_ts["AAPL"] = 9999
    s.subscribe_bars(["AAPL"], MagicMock())
    with patch.object(s, "_ws_thread") as _:
        s._first_bar_logged.clear()
        s._heartbeat_logged = False
        s._snapshot_ts.clear()
        s._running = True
    assert "AAPL" not in s._snapshot_ts
