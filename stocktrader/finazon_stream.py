"""
FinazonBarStream — live 1m SIP bars via Finazon WebSocket.

Dataset: us_stocks_essential (100% US marktdekking via SIP).
Vereist: FINAZON_API_KEY (abonnement 'US Equities Basic', ~$19/mnd voor non-pro).

Docs: https://finazon.io/dataset/us_stocks_essential/docs/ws/latest

WS-URL:     wss://ws.finazon.io/v1?apikey={key}
Subscribe:  {"event":"subscribe","dataset":"us_stocks_essential",
             "tickers":["AAPL"],"channel":"bars","frequency":"1m","aggregation":"1m"}
Bar-bericht:{"s":"AAPL","t":1699540020,"o":220.06,"h":220.13,"l":219.92,"c":219.96,"v":4572,...}

Bars worden verzonden bij elke minuut-grens (frequency=1m).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Callable, Dict, List, Optional, Set

BarHandler = Callable[..., None]

_WS_BASE      = "wss://ws.finazon.io/v1"
_DATASET      = "us_stocks_essential"
_BACKOFF_MAX  = 60

_UNSUPPORTED_TICKER_RE = re.compile(
    r"ticker\s+([A-Z][A-Z0-9.]{0,5})\s+you have specified",
    re.IGNORECASE,
)
_ALREADY_SUBSCRIBED_RE = re.compile(r"already subscribed", re.IGNORECASE)


def _is_finazon_auth_error(msg: str) -> bool:
    lower = msg.lower()
    return any(
        k in lower
        for k in ("api key", "unauthorized", "invalid key", "authentication", "forbidden")
    )


class FinazonBarStream:
    """
    Real-time 1m SIP bar-stream via Finazon WebSocket.
    Zelfde interface als YfinanceBarStream / PolygonBarStream / AlpacaBarStream.
    """

    def __init__(self, api_key: str, dataset: str = _DATASET) -> None:
        if not api_key:
            raise RuntimeError(
                "FINAZON_API_KEY is verplicht voor DATA_SOURCE=finazon"
            )
        self._api_key = api_key
        self._dataset = dataset
        self._callbacks: Dict[str, BarHandler] = {}
        self._callbacks_lock = threading.Lock()
        self._skipped: Set[str] = set()
        self._exclusion_handler: Optional[Callable[[str], None]] = None
        self._first_bar_logged: Set[str] = set()
        self._heartbeat_logged = False
        self._running = False
        self._ws = None
        self._ws_thread: Optional[threading.Thread] = None

    def set_exclusion_handler(self, handler: Optional[Callable[[str], None]]) -> None:
        self._exclusion_handler = handler

    def get_skipped_tickers(self) -> Set[str]:
        with self._callbacks_lock:
            return set(self._skipped)

    def subscribe_bars(self, tickers: List[str], on_bar: BarHandler) -> None:
        with self._callbacks_lock:
            for ticker in tickers:
                self._callbacks[ticker] = on_bar

    def start_stream(self) -> None:
        if self._running:
            return
        with self._callbacks_lock:
            n = len(self._callbacks)
        if n == 0:
            logging.warning("FinazonBarStream: geen tickers geregistreerd vóór start.")
        self._first_bar_logged.clear()
        self._heartbeat_logged = False
        self._running = True
        self._ws_thread = threading.Thread(
            target=self._run_ws, daemon=True, name="finazon-ws"
        )
        self._ws_thread.start()
        logging.info(
            "Finazon bar-stream gestart (dataset=%s, tickers=%d)",
            self._dataset, n,
        )

    def stop_stream(self) -> None:
        self._running = False
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        logging.info("Finazon bar-stream gestopt.")

    # ------------------------------------------------------------------
    # WebSocket leven-cyclus
    # ------------------------------------------------------------------

    def _run_ws(self) -> None:
        try:
            import websocket  # websocket-client
        except ImportError:
            logging.error(
                "websocket-client niet gevonden. "
                "Installeer: pip install websocket-client>=1.7.0"
            )
            return

        url = f"{_WS_BASE}?apikey={self._api_key}"
        backoff = 5

        while self._running:
            try:
                ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws = ws
                ws.run_forever(ping_interval=30, ping_timeout=10)
                backoff = 5  # reset na succesvolle sessie
            except Exception as exc:
                logging.warning("Finazon WS run_forever fout: %s", exc)

            if not self._running:
                break

            logging.info("Finazon WS opnieuw verbinden in %ds...", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)

    def _send_subscribe(self, ws) -> bool:
        with self._callbacks_lock:
            tickers = list(self._callbacks.keys())
        if not tickers:
            logging.warning("Finazon: geen ondersteunde tickers meer — stream stopt.")
            self._running = False
            try:
                ws.close()
            except Exception:
                pass
            return False
        payload = {
            "event": "subscribe",
            "dataset": self._dataset,
            "tickers": tickers,
            "channel": "bars",
            "frequency": "1m",
            "aggregation": "1m",
        }
        try:
            ws.send(json.dumps(payload))
            return True
        except Exception as exc:
            logging.warning("Finazon WS subscribe-send mislukt: %s", exc)
            return False

    def _on_open(self, ws) -> None:
        with self._callbacks_lock:
            n = len(self._callbacks)
        logging.info("Finazon WS verbonden — subscriben op %d tickers...", n)
        self._send_subscribe(ws)

    def _on_message(self, ws, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            return

        status = msg.get("status")
        event  = msg.get("event")

        if status == "success" and msg.get("code") == "SUCCESS_SUBSCRIPTION":
            logging.info(
                "Finazon WS: subscriptie bevestigd voor %d symbolen.",
                len(msg.get("data", [])),
            )
            return

        if status == "error":
            err_msg = str(msg.get("message", msg))
            if _is_finazon_auth_error(err_msg):
                logging.error("Finazon WS auth-fout: %s", err_msg)
                self._running = False
                try:
                    ws.close()
                except Exception:
                    pass
                return

            if _ALREADY_SUBSCRIBED_RE.search(err_msg):
                logging.debug("Finazon WS: %s", err_msg)
                return

            m = _UNSUPPORTED_TICKER_RE.search(err_msg)
            if m:
                bad = m.group(1).upper()
                with self._callbacks_lock:
                    if bad in self._skipped:
                        return
                    self._callbacks.pop(bad, None)
                    self._skipped.add(bad)
                    remaining = len(self._callbacks)
                logging.warning(
                    "Finazon: %s niet ondersteund — overgeslagen, %d tickers over.",
                    bad, remaining,
                )
                handler = self._exclusion_handler
                if handler is not None:
                    try:
                        handler(bad)
                    except Exception as exc:
                        logging.warning("Finazon exclusion handler: %s", exc)
                # Geen resubscribe: geldige tickers uit hetzelfde batch-bericht
                # zijn al actief bij Finazon.
                return

            logging.error("Finazon WS subscriptiefout: %s", err_msg)
            return

        if event == "heartbeat":
            if not self._heartbeat_logged:
                self._heartbeat_logged = True
                logging.info("Finazon WS heartbeat ontvangen — verbinding actief.")
            return

        # Bar-bericht: heeft "s" (symbool) en OHLCV velden
        if "s" in msg and "o" in msg:
            self._emit_bar(msg)

    def _on_error(self, ws, error) -> None:
        # Redacteer API key uit error-berichten
        err_str = str(error).replace(self._api_key, "***")
        logging.warning("Finazon WS error: %s", err_str)

    def _on_close(self, ws, code, reason) -> None:
        logging.info("Finazon WS gesloten (code=%s, reason=%s).", code, reason)

    def _emit_bar(self, msg: dict) -> None:
        ticker = msg.get("s", "")
        with self._callbacks_lock:
            handler = self._callbacks.get(ticker)
        if handler is None:
            return
        if ticker and ticker not in self._first_bar_logged:
            self._first_bar_logged.add(ticker)
            logging.info(
                "Finazon eerste bar: %s C=%.4f V=%.0f",
                ticker, float(msg.get("c", 0)), float(msg.get("v", 0)),
            )
        try:
            handler(
                ticker,
                float(msg["o"]),
                float(msg["h"]),
                float(msg["l"]),
                float(msg["c"]),
                float(msg["v"]),
                True,
            )
        except Exception as exc:
            logging.warning("FinazonBarStream emit_bar %s: %s", ticker, exc)
