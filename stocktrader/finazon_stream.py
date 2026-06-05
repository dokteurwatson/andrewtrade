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
import threading
import time
from typing import Callable, Dict, List, Optional

BarHandler = Callable[..., None]

_WS_BASE      = "wss://ws.finazon.io/v1"
_DATASET      = "us_stocks_essential"
_BACKOFF_MAX  = 60


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
        self._running = False
        self._ws = None
        self._ws_thread: Optional[threading.Thread] = None

    def subscribe_bars(self, tickers: List[str], on_bar: BarHandler) -> None:
        for ticker in tickers:
            self._callbacks[ticker] = on_bar

    def start_stream(self) -> None:
        if self._running:
            return
        if not self._callbacks:
            logging.warning("FinazonBarStream: geen tickers geregistreerd vóór start.")
        self._running = True
        self._ws_thread = threading.Thread(
            target=self._run_ws, daemon=True, name="finazon-ws"
        )
        self._ws_thread.start()
        logging.info(
            "Finazon bar-stream gestart (dataset=%s, tickers=%d)",
            self._dataset, len(self._callbacks),
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
            except Exception as exc:
                logging.warning("Finazon WS run_forever fout: %s", exc)

            if not self._running:
                break

            logging.info("Finazon WS opnieuw verbinden in %ds...", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)

    def _on_open(self, ws) -> None:
        logging.info("Finazon WS verbonden — subscriben op %d tickers...", len(self._callbacks))
        tickers = list(self._callbacks.keys())
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
        except Exception as exc:
            logging.warning("Finazon WS subscribe-send mislukt: %s", exc)

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
            logging.error(
                "Finazon WS subscriptiefout: %s", msg.get("message", msg)
            )
            return

        if event == "heartbeat":
            return

        # Bar-bericht: heeft "s" (symbool) en OHLCV velden
        if "s" in msg and "o" in msg:
            self._emit_bar(msg)

    def _on_error(self, ws, error) -> None:
        logging.warning("Finazon WS error: %s", error)

    def _on_close(self, ws, code, reason) -> None:
        logging.info("Finazon WS gesloten (code=%s, reason=%s).", code, reason)

    def _emit_bar(self, msg: dict) -> None:
        ticker  = msg.get("s", "")
        handler = self._callbacks.get(ticker)
        if handler is None:
            return
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
