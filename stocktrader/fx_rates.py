"""
Live FX-rates voor T212 position sizing (EUR/GBP account → USD tickers).

T212 wisselt zelf om bij orderuitvoering; dit is alleen een schatting
vóór het plaatsen van quantity-orders, met buffer tegen spread/fees.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple

_CACHE_TTL_SEC = 300.0
_cache: Dict[str, Tuple[float, float]] = {}  # pair → (rate, monotonic_ts)

_PAIR_TICKERS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
}


def _fetch_live_rate(pair: str) -> Optional[float]:
    """Lightweight Yahoo chart call — geen yfinance (voorkomt DEBUG-spam)."""
    symbol = _PAIR_TICKERS.get(pair)
    if not symbol:
        return None
    try:
        q = urllib.parse.quote(symbol, safe="")
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{q}"
            "?range=1d&interval=1d"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "stocktrader-fx/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode())
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        for key in ("regularMarketPrice", "previousClose"):
            val = meta.get(key)
            if val is not None and float(val) > 0:
                return float(val)
    except Exception as exc:
        logging.debug("FX %s ophalen mislukt: %s", pair, exc)
    return None


def get_rate_to_usd(
    currency: str,
    *,
    fallback_eur_usd: float,
    fallback_gbp_usd: float,
    buffer_pct: float = 0.03,
) -> float:
    """
    1 eenheid accountvaluta → USD, met safety-buffer (default 3%).
    Fallback naar env als live FX niet beschikbaar is.
    """
    ccy = currency.upper()
    if ccy == "USD":
        return 1.0

    pair = {"EUR": "EURUSD", "GBP": "GBPUSD"}.get(ccy)
    fallback = {"EUR": fallback_eur_usd, "GBP": fallback_gbp_usd}.get(ccy)
    if pair is None or fallback is None:
        return 1.0

    now = time.monotonic()
    cached = _cache.get(pair)
    if cached and now - cached[1] < _CACHE_TTL_SEC:
        rate = cached[0]
    else:
        live = _fetch_live_rate(pair)
        if live is not None:
            rate = live
            _cache[pair] = (rate, now)
            logging.info("FX %s live: %.4f (voor US-sizing schatting)", pair, rate)
        else:
            rate = fallback
            logging.debug("FX %s fallback env: %.4f", pair, rate)

    return rate * (1.0 - max(0.0, buffer_pct))


def convert_usd_to_account(
    amount_usd: float,
    currency: str,
    *,
    fallback_eur_usd: float,
    fallback_gbp_usd: float,
) -> float:
    """USD → accountvaluta (geen sizing-buffer; voor PnL-weergave)."""
    ccy = currency.upper()
    if ccy == "USD":
        return amount_usd
    rate = get_rate_to_usd(
        ccy,
        fallback_eur_usd=fallback_eur_usd,
        fallback_gbp_usd=fallback_gbp_usd,
        buffer_pct=0.0,
    )
    if rate <= 0:
        return amount_usd
    return amount_usd / rate
