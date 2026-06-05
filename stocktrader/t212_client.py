"""
T212Client — Trading 212 REST API broker-client.

Ondersteunt demo (demo.trading212.com) en live (live.trading212.com).
Env:
    BROKER=t212
    T212_API_KEY=<jouw API key>
    T212_API_SECRET=<jouw API secret>   # Basic auth (key:secret, aanbevolen)
    T212_DEMO=true     → demo  |  false → live (echt geld)

Auth:
    Modern (aanbevolen): Basic auth — Authorization: Basic base64(key:secret)
    Legacy (fallback):   Authorization: <key>   (als T212_API_SECRET leeg is)

Interface gelijk aan PaperClient:
    connect() / disconnect()
    get_cash() / get_buying_power()
    is_tradable(ticker) / get_latest_price(ticker)
    buy_market(ticker, shares) → order_id
    sell_market(ticker, shares) → order_id  (T212: quantity negatief voor verkoop)
    close_all_positions()
    bind_state(store, state)  — no-op (cash leeft in T212)
"""
from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from .state import DayState, StateStore

_DEMO_BASE = "https://demo.trading212.com/api/v0"
_LIVE_BASE = "https://live.trading212.com/api/v0"

_MIN_CALL_INTERVAL = 0.25  # seconden tussen API-calls (T212 rate limits)


class T212Client:
    """
    Broker-client voor Trading 212 (Invest/ISA, US equities).

    Ticker-mapping: bij connect() worden alle instrumenten opgehaald en
    een shortName → T212-ticker dict gebouwd (bv. AAPL → AAPL_US_EQ).
    """

    def __init__(self, api_key: str, api_secret: str = "", *, demo: bool = True) -> None:
        if not api_key:
            raise RuntimeError("T212_API_KEY is verplicht voor BROKER=t212")
        self._api_key    = api_key
        self._api_secret = api_secret
        self._base = _DEMO_BASE if demo else _LIVE_BASE
        self._mode = "DEMO" if demo else "LIVE"
        self._instrument_map: Dict[str, str] = {}  # shortName.upper() → t212_ticker
        self._price_cache: Dict[str, float] = {}
        self._last_call_ts: float = 0.0

    # ------------------------------------------------------------------
    # Verbinding
    # ------------------------------------------------------------------

    def connect(self) -> None:
        logging.info("T212Client: verbinden met %s (%s)...", self._base, self._mode)
        self._load_instruments()
        logging.info(
            "T212Client verbonden [%s] | %d instrumenten geladen.",
            self._mode, len(self._instrument_map),
        )

    def disconnect(self) -> None:
        logging.info("T212Client: losgekoppeld.")

    def bind_state(self, store: "StateStore", state: "DayState") -> None:
        """No-op: cash leeft in T212, niet in lokale state."""

    # ------------------------------------------------------------------
    # Instrumenten
    # ------------------------------------------------------------------

    def _load_instruments(self) -> None:
        """Haal alle T212-instrumenten op en bouw shortName → ticker map."""
        data = self._get("/equity/metadata/instruments")
        instruments: List[dict] = data if isinstance(data, list) else []
        mapping: Dict[str, str] = {}
        for inst in instruments:
            t212_ticker = inst.get("ticker", "")
            short = inst.get("shortName", "")
            if not t212_ticker or not short:
                continue
            key = short.upper()
            # Prefereer US equity boven andere markten voor dezelfde shortName
            if key not in mapping or "_US_EQ" in t212_ticker:
                mapping[key] = t212_ticker
        self._instrument_map = mapping
        logging.debug("T212 instrument-map: %d entries", len(mapping))

    def _map_ticker(self, ticker: str) -> str:
        """Zet shortName (AAPL) om naar T212-ticker (AAPL_US_EQ). Gooit ValueError als onbekend."""
        t212 = self._instrument_map.get(ticker.upper())
        if not t212:
            raise ValueError(
                f"Ticker '{ticker}' niet gevonden in T212 instrument-map. "
                "Controleer of het instrument verhandelbaar is op je T212-account."
            )
        return t212

    def is_tradable(self, ticker: str) -> bool:
        return ticker.upper() in self._instrument_map

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_cash(self) -> float:
        try:
            data = self._get("/equity/account/summary")
            cash_block = data.get("cash", data)
            for field in ("free", "availableToTrade", "freeForStocks"):
                val = cash_block.get(field)
                if val is not None:
                    return float(val)
        except Exception as exc:
            logging.warning("T212 get_cash mislukt: %s", exc)
        return 0.0

    def get_buying_power(self) -> float:
        return self.get_cash()

    # ------------------------------------------------------------------
    # Prijzen
    # ------------------------------------------------------------------

    def update_last_price(self, ticker: str, price: float) -> None:
        """Wordt aangeroepen vanuit de bar-stream zodat we altijd een verse prijs hebben."""
        self._price_cache[ticker] = price

    def get_latest_price(self, ticker: str) -> Optional[float]:
        cached = self._price_cache.get(ticker)
        if cached:
            return cached
        # Fallback: probeer T212-positie als die bestaat
        try:
            t212 = self._map_ticker(ticker)
            data = self._get(f"/equity/positions/{urllib.parse.quote(t212)}")
            price = data.get("currentPrice")
            if price is not None:
                return float(price)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def buy_market(self, ticker: str, shares: int) -> str:
        t212 = self._map_ticker(ticker)
        payload = {
            "ticker": t212,
            "quantity": abs(shares),
            "type": "MARKET",
            "timeValidity": "DAY",
        }
        response = self._post("/equity/orders/market", payload)
        order_id = str(response.get("id", f"t212-buy-{ticker}-{int(time.time())}"))
        logging.info(
            "T212 BUY %s x%d [%s] → order_id=%s",
            ticker, shares, self._mode, order_id,
        )
        return order_id

    def sell_market(self, ticker: str, shares: int) -> str:
        t212 = self._map_ticker(ticker)
        # T212 API: negatieve quantity = verkoop
        payload = {
            "ticker": t212,
            "quantity": -abs(shares),
            "type": "MARKET",
            "timeValidity": "DAY",
        }
        response = self._post("/equity/orders/market", payload)
        order_id = str(response.get("id", f"t212-sell-{ticker}-{int(time.time())}"))
        logging.info(
            "T212 SELL %s x%d [%s] → order_id=%s",
            ticker, shares, self._mode, order_id,
        )
        return order_id

    def close_all_positions(self) -> None:
        """Sluit alle open T212-posities via market sell-orders."""
        try:
            positions = self._get("/equity/positions")
        except Exception as exc:
            logging.error("T212 close_all_positions: posities ophalen mislukt: %s", exc)
            return

        if not positions:
            logging.info("T212 EOD: geen open posities gevonden.")
            return

        logging.info("T212 EOD: %d posities sluiten...", len(positions))
        for pos in positions:
            t212_ticker = pos.get("ticker", "")
            qty = pos.get("quantity", 0)
            if not t212_ticker or qty <= 0:
                continue
            # Reverse-lookup voor logging (niet kritiek als niet gevonden)
            short = self._reverse_ticker(t212_ticker)
            try:
                payload = {
                    "ticker": t212_ticker,
                    "quantity": -abs(qty),  # negatief = verkoop
                    "type": "MARKET",
                    "timeValidity": "DAY",
                }
                self._post("/equity/orders/market", payload)
                logging.info("T212 EOD close: %s x%.4f", short or t212_ticker, qty)
            except Exception as exc:
                logging.error(
                    "T212 EOD close mislukt voor %s: %s", short or t212_ticker, exc
                )

    def _reverse_ticker(self, t212_ticker: str) -> str:
        for short, t212 in self._instrument_map.items():
            if t212 == t212_ticker:
                return short
        return t212_ticker

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = _MIN_CALL_INTERVAL - (now - self._last_call_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_call_ts = time.monotonic()

    def _auth_header(self) -> str:
        if self._api_secret:
            creds = base64.b64encode(
                f"{self._api_key}:{self._api_secret}".encode()
            ).decode()
            return f"Basic {creds}"
        return self._api_key  # legacy header-only

    def _headers(self) -> dict:
        return {
            "Authorization": self._auth_header(),
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> any:
        self._throttle()
        url = self._base + path
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"T212 GET {path} → HTTP {exc.code}: {body}") from exc

    def _post(self, path: str, payload: dict) -> dict:
        self._throttle()
        url = self._base + path
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"T212 POST {path} → HTTP {exc.code}: {body}") from exc


# urllib.parse ontbreekt zonder expliciete import in module scope
import urllib.parse  # noqa: E402
