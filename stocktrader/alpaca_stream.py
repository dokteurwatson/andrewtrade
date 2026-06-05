"""
AlpacaBarStream — live 1m bars via Alpaca WebSocket (IEX of SIP feed).

Gratis paper-account krijgt IEX real-time data.
Paid Algo Trader Plus ($99) geeft toegang tot SIP (volledige markt).

Env:
    ALPACA_API_KEY    — key ID van paper of live account
    ALPACA_API_SECRET — secret van paper of live account
    ALPACA_DATA_FEED  — iex (default) | sip
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable, Dict, List, Optional

BarHandler = Callable[..., None]

_WS_BASE = "wss://stream.data.alpaca.markets/v2/{feed}"
_BACKOFF_MAX = 60


class AlpacaBarStream:
    """
    WebSocket-gebaseerde 1m bar-stream via Alpaca Market Data API.
    Zelfde interface als YfinanceBarStream / PolygonBarStream:
      subscribe_bars(tickers, on_bar) → start_stream() → stop_stream()
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        feed: str = "iex",
    ) -> None:
        if not api_key or not api_secret:
            raise RuntimeError(
                "ALPACA_API_KEY en ALPACA_API_SECRET zijn verplicht voor DATA_SOURCE=alpaca"
            )
        self._key = api_key
        self._secret = api_secret
        self._feed = feed.lower()
        self._callbacks: Dict[str, BarHandler] = {}
        self._running = False
        self._ws_thread: Optional[threading.Thread] = None
        self._ws = None
        self._authenticated = False

    def subscribe_bars(self, tickers: List[str], on_bar: BarHandler) -> None:
        for ticker in tickers:
            self._callbacks[ticker] = on_bar

    def start_stream(self) -> None:
        if self._running:
            return
        if not self._callbacks:
            logging.warning("AlpacaBarStream: geen tickers geregistreerd vóór start.")
        self._running = True
        self._ws_thread = threading.Thread(
            target=self._run_ws, daemon=True, name="alpaca-ws"
        )
        self._ws_thread.start()
        logging.info(
            "Alpaca bar-stream gestart (feed=%s, tickers=%d)",
            self._feed, len(self._callbacks),
        )

    def stop_stream(self) -> None:
        self._running = False
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        logging.info("Alpaca bar-stream gestopt.")

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

        url = _WS_BASE.format(feed=self._feed)
        backoff = 5

        while self._running:
            self._authenticated = False
            try:
                ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws = ws
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:
                logging.warning("Alpaca WS run_forever fout: %s", exc)

            if not self._running:
                break

            logging.info("Alpaca WS opnieuw verbinden in %ds...", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)

    def _on_open(self, ws) -> None:
        logging.debug("Alpaca WS socket open.")

    def _on_message(self, ws, raw: str) -> None:
        try:
            msgs = json.loads(raw)
        except Exception:
            return
        if not isinstance(msgs, list):
            msgs = [msgs]
        for msg in msgs:
            self._handle_msg(ws, msg)

    def _on_error(self, ws, error) -> None:
        logging.warning("Alpaca WS error: %s", error)

    def _on_close(self, ws, code, reason) -> None:
        logging.info("Alpaca WS gesloten (code=%s, reason=%s).", code, reason)

    # ------------------------------------------------------------------
    # Protocol
    # ------------------------------------------------------------------

    def _handle_msg(self, ws, msg: dict) -> None:
        t = msg.get("T")

        if t == "success":
            srv_msg = msg.get("msg", "")
            if srv_msg == "connected":
                logging.info("Alpaca WS verbonden — authenticeren...")
                self._send(ws, {"action": "auth", "key": self._key, "secret": self._secret})
            elif srv_msg == "authenticated":
                self._authenticated = True
                logging.info("Alpaca WS geauthenticeerd (feed=%s).", self._feed)
                tickers = list(self._callbacks.keys())
                self._send(ws, {"action": "subscribe", "bars": tickers})

        elif t == "subscription":
            bars = msg.get("bars", [])
            logging.info("Alpaca WS geabonneerd op %d bar-feeds: %s", len(bars), bars)

        elif t == "error":
            code = msg.get("code")
            err_msg = msg.get("msg", "")
            logging.error("Alpaca WS protocol-fout code=%s: %s", code, err_msg)
            if code in (402, 403):
                logging.error("Alpaca auth mislukt — stream stopt.")
                self._running = False
                ws.close()

        elif t == "b":
            self._emit_bar(msg)

    def _send(self, ws, payload: dict) -> None:
        try:
            ws.send(json.dumps(payload))
        except Exception as exc:
            logging.warning("Alpaca WS send mislukt: %s", exc)

    def _emit_bar(self, msg: dict) -> None:
        ticker = msg.get("S", "")
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
            logging.warning("AlpacaBarStream emit_bar %s: %s", ticker, exc)
