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
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from .state import DayState, StateStore

_DEMO_BASE = "https://demo.trading212.com/api/v0"
_LIVE_BASE = "https://live.trading212.com/api/v0"

_MIN_CALL_INTERVAL = 0.25  # seconden tussen API-calls (T212 rate limits)
_MAX_RETRIES = 3
_CASH_CACHE_TTL = 45.0  # seconden — voorkom parallelle get_cash() spam

CURRENCY_SYMBOLS: Dict[str, str] = {"USD": "$", "EUR": "€", "GBP": "£"}


@dataclass(frozen=True)
class T212AccountInfo:
    cash: float
    currency: str  # ISO 4217, account primary currency (T212 API)


def currency_symbol(code: str) -> str:
    return CURRENCY_SYMBOLS.get(code.upper(), f"{code.upper()} ")


class T212Error(RuntimeError):
    """Basis T212 API-fout."""


class T212AuthError(T212Error):
    """401/403 — ongeldige credentials."""


class T212RateLimitError(T212Error):
    """429 — rate limit bereikt."""

    def __init__(self, message: str, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class T212NetworkError(T212Error):
    """Netwerk/timeout fout — transient, retry mogelijk."""


class T212PositionNotFoundError(T212Error):
    """Positie niet gevonden bij broker — lokale state desync."""


class T212CloseOnlyError(T212Error):
    """Instrument staat in close-only mode — geen nieuwe buys."""


class T212ExtendedHoursNotAllowedError(T212Error):
    """Account ondersteunt geen extended-hours orders."""


def _is_position_gone_message(msg: str) -> bool:
    lower = msg.lower()
    return any(
        k in lower
        for k in ("position", "not found", "no position", "insufficient", "does not exist")
    )


class T212Client:
    """
    Broker-client voor Trading 212 (Invest/ISA, US equities).

    Ticker-mapping: bij connect() worden alle instrumenten opgehaald en
    een shortName → T212-ticker dict gebouwd (bv. AAPL → AAPL_US_EQ).
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str = "",
        *,
        demo: bool = True,
        extended_hours: bool = True,
        fx_eur_usd: float = 1.08,
        fx_gbp_usd: float = 1.27,
        fx_buffer_pct: float = 0.03,
    ) -> None:
        if not api_key:
            raise RuntimeError("T212_API_KEY is verplicht voor BROKER=t212")
        self._api_key    = api_key
        self._api_secret = api_secret
        self._extended_hours = extended_hours
        self._fx_eur_usd = fx_eur_usd
        self._fx_gbp_usd = fx_gbp_usd
        self._fx_buffer_pct = fx_buffer_pct
        self._base = _DEMO_BASE if demo else _LIVE_BASE
        self._mode = "DEMO" if demo else "LIVE"
        self._instrument_map: Dict[str, str] = {}  # shortName.upper() → t212_ticker
        self._price_cache: Dict[str, float] = {}
        self._last_call_ts: float = 0.0
        self._connected = False
        self._account_cache: Optional[T212AccountInfo] = None
        self._cash_cache_ts: float = 0.0

    # ------------------------------------------------------------------
    # Verbinding
    # ------------------------------------------------------------------

    def connect(self) -> None:
        if self._connected:
            return
        logging.info("T212Client: verbinden met %s (%s)...", self._base, self._mode)
        self._load_instruments()
        self._connected = True
        logging.info(
            "T212Client verbonden [%s] | %d instrumenten geladen.",
            self._mode, len(self._instrument_map),
        )

    def _ensure_connected(self) -> None:
        """Lazy connect — nodig voor is_tradable/get_cash vóór trader-start."""
        if not self._connected:
            self.connect()

    def disconnect(self) -> None:
        self._connected = False
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
        self._ensure_connected()
        return ticker.upper() in self._instrument_map

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def _parse_account_summary(self, data: dict) -> T212AccountInfo:
        cash_block = data.get("cash", data)
        cash = 0.0
        # availableToTrade = werkelijk vrij om te handelen; "free" kan te hoog zijn
        for field in ("availableToTrade", "freeForStocks", "free"):
            val = cash_block.get(field)
            if val is not None:
                cash = float(val)
                break
        currency = str(data.get("currency", "USD")).upper()
        return T212AccountInfo(cash=cash, currency=currency)

    def get_account_info(self, *, force: bool = False) -> T212AccountInfo:
        now = time.monotonic()
        if (
            not force
            and self._account_cache is not None
            and now - self._cash_cache_ts < _CASH_CACHE_TTL
        ):
            return self._account_cache
        self._ensure_connected()
        data = self._get("/equity/account/summary")
        info = self._parse_account_summary(data)
        self._account_cache = info
        self._cash_cache_ts = time.monotonic()
        return info

    def get_cash(self, *, force: bool = False) -> float:
        return self.get_account_info(force=force).cash

    def invalidate_account_cache(self) -> None:
        """Na orders: cache legen zodat volgende get_cash() vers is."""
        self._account_cache = None
        self._cash_cache_ts = 0.0

    def get_account_currency(self) -> str:
        if self._account_cache is not None:
            return self._account_cache.currency
        return self.get_account_info().currency

    def get_account_currency_cached(self, default: str = "EUR") -> str:
        """Alleen cache — geen API (veilig voor dashboard request-path)."""
        if self._account_cache is not None:
            return self._account_cache.currency
        return default

    def cash_in_usd(self, amount: float, *, currency: Optional[str] = None) -> float:
        """
        Schatting: account-saldo → USD voor share-count vóór de order.

        T212 wisselt live om bij uitvoering; dit is geen conversie door ons.
        """
        from .fx_rates import get_rate_to_usd

        ccy = (currency or self.get_account_currency()).upper()
        rate = get_rate_to_usd(
            ccy,
            fallback_eur_usd=self._fx_eur_usd,
            fallback_gbp_usd=self._fx_gbp_usd,
            buffer_pct=self._fx_buffer_pct,
        )
        if ccy != "USD" and rate == 1.0:
            logging.warning(
                "T212: onbekende accountvaluta %s — geen FX, sizing kan afwijken.",
                ccy,
            )
        return amount * rate

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
        if cached is not None and cached > 0:
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

    def extended_hours_enabled(self) -> bool:
        return self._extended_hours

    def disable_extended_hours(self) -> None:
        if self._extended_hours:
            logging.info("T212 extended hours uitgeschakeld (account ondersteunt het niet).")
        self._extended_hours = False

    def _market_payload(self, t212_ticker: str, quantity: float) -> dict:
        """T212 MarketRequest: alleen ticker, quantity (+ optioneel extendedHours)."""
        payload: dict = {"ticker": t212_ticker, "quantity": quantity}
        if self._extended_hours:
            payload["extendedHours"] = True
        return payload

    def buy_market(self, ticker: str, shares: int) -> str:
        t212 = self._map_ticker(ticker)
        payload = self._market_payload(t212, abs(shares))
        response = self._post("/equity/orders/market", payload)
        order_id = str(response.get("id", f"t212-buy-{ticker}-{int(time.time())}"))
        self.invalidate_account_cache()
        logging.info(
            "T212 BUY %s x%d [%s] → order_id=%s",
            ticker, shares, self._mode, order_id,
        )
        return order_id

    def sell_market(self, ticker: str, shares: int) -> str:
        t212 = self._map_ticker(ticker)
        # T212 API: negatieve quantity = verkoop
        payload = self._market_payload(t212, -abs(shares))
        try:
            response = self._post("/equity/orders/market", payload)
        except T212Error as exc:
            if _is_position_gone_message(str(exc)):
                raise T212PositionNotFoundError(str(exc)) from exc
            raise
        order_id = str(response.get("id", f"t212-sell-{ticker}-{int(time.time())}"))
        self.invalidate_account_cache()
        logging.info(
            "T212 SELL %s x%d [%s] → order_id=%s",
            ticker, shares, self._mode, order_id,
        )
        return order_id

    def get_order_fill_price(
        self, order_id: str, *, timeout: float = 6.0, poll_interval: float = 0.5
    ) -> Optional[float]:
        """
        Poll T212 order-endpoint voor werkelijke fill-prijs (USD).

        T212 market orders worden doorgaans binnen 1–2s uitgevoerd.
        Geeft None terug als de order niet gevuld is binnen de timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data = self._get(f"/equity/orders/{order_id}")
                status = data.get("status", "")
                if status == "FILLED":
                    # averagePrice is in instrument currency (USD voor US stocks)
                    avg = data.get("averagePrice") or data.get("fillPrice")
                    if avg:
                        price = float(avg)
                        logging.info(
                            "T212 fill-prijs order %s: $%.4f", order_id, price
                        )
                        return price
                    logging.debug(
                        "T212 order %s FILLED maar geen averagePrice in response: %s",
                        order_id, list(data.keys()),
                    )
                    return None
                if status in ("CANCELLED", "REJECTED"):
                    logging.warning(
                        "T212 order %s status=%s — geen fill-prijs.", order_id, status
                    )
                    return None
            except Exception as exc:
                logging.debug("T212 order-poll %s: %s", order_id, exc)
            time.sleep(poll_interval)
        logging.debug(
            "T212 order %s niet gevuld binnen %.0fs — bar-prijs als fallback.",
            order_id, timeout,
        )
        return None

    def close_all_positions(self) -> None:
        """Sluit alle open T212-posities via market sell-orders."""
        try:
            positions = self._get("/equity/positions")
        except T212Error as exc:
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
                payload = self._market_payload(t212_ticker, -abs(qty))
                self._post("/equity/orders/market", payload)
                logging.info("T212 EOD close: %s x%.4f", short or t212_ticker, qty)
            except T212Error as exc:
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
            "User-Agent": "stocktrader/1.0 (T212 API client)",
            "Accept": "application/json",
        }

    def _classify_http_error(self, exc: urllib.error.HTTPError, path: str, body: str) -> T212Error:
        code = exc.code
        msg = f"T212 {path} → HTTP {code}: {body}"
        # Cloudflare WAF (error code 1010) ≠ ongeldige API-key
        if "error code: 1010" in body.lower() or "cloudflare" in body.lower():
            return T212NetworkError(
                f"T212 {path} geblokkeerd door Cloudflare (HTTP {code}). "
                "Mogelijk datacenter-IP of ontbrekende browser-headers."
            )
        if code == 401:
            return T212AuthError(msg)
        if code == 403:
            return T212AuthError(msg)
        if code == 429:
            retry_after = 0.0
            try:
                retry_after = float(exc.headers.get("Retry-After", 0))
            except (TypeError, ValueError):
                pass
            return T212RateLimitError(msg, retry_after=retry_after)
        if _is_position_gone_message(body):
            return T212PositionNotFoundError(msg)
        lower = body.lower()
        if "close-only-mode" in lower or "close only mode" in lower:
            return T212CloseOnlyError(msg)
        if "extended-hours-trading-not-allowed" in lower:
            return T212ExtendedHoursNotAllowedError(msg)
        return T212Error(msg)

    def _request_with_retry(self, method: str, path: str, payload: Optional[dict] = None) -> any:
        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES):
            self._throttle()
            url = self._base + path
            try:
                if method == "GET":
                    req = urllib.request.Request(url, headers=self._headers())
                    with urllib.request.urlopen(req, timeout=15) as r:
                        return json.loads(r.read())
                data = json.dumps(payload).encode()
                req = urllib.request.Request(
                    url, data=data, headers=self._headers(), method="POST"
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                classified = self._classify_http_error(exc, path, body)
                if isinstance(classified, T212RateLimitError):
                    wait = classified.retry_after or (2 ** attempt)
                    logging.warning(
                        "T212 rate limit %s (poging %d/%d), wacht %.1fs",
                        path, attempt + 1, _MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    last_exc = classified
                    continue
                raise classified from exc
            except urllib.error.URLError as exc:
                wait = 2 ** attempt
                logging.warning(
                    "T212 netwerk %s (poging %d/%d): %s — retry in %.1fs",
                    path, attempt + 1, _MAX_RETRIES, exc, wait,
                )
                last_exc = T212NetworkError(f"T212 {path} netwerk: {exc}")
                time.sleep(wait)
                continue
        if last_exc:
            raise last_exc
        raise T212NetworkError(f"T212 {path}: max retries bereikt")

    def _get(self, path: str) -> any:
        return self._request_with_retry("GET", path)

    def _post(self, path: str, payload: dict) -> dict:
        return self._request_with_retry("POST", path, payload)
