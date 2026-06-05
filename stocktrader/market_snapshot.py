"""
Markt-quotes voor dashboard en backtests.

- Live dashboard (finazon/alpaca/polygon): via Trader-barstate — zelfde bron als signalen.
- Dashboard dev (DATA_SOURCE=yfinance): yfinance 1m (~15 min delay).
- Backtests: yfinance via fetch_1m / build_quote_row.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import date
from typing import Dict, List, Optional, Tuple

from .config import Settings
from .market_data import fetch_1m, orb_avg_volume
from .parser import Setup

_CACHE_TTL_SEC = 55
_REF_CACHE_TTL_SEC = 300.0
_yfinance_cache: Dict[str, object] = {"ts": 0.0, "rows": []}
_ref_price_cache: Dict[str, Tuple[float, str, float]] = {}  # ticker → (price, label, mono_ts)


def _fetch_reference_price_yahoo(ticker: str) -> Tuple[Optional[float], str]:
    """Vorige slot / pre-market via Yahoo chart (geen yfinance)."""
    try:
        q = urllib.parse.quote(ticker, safe="")
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{q}"
            "?range=1d&interval=1d"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "stocktrader-ref/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode())
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return None, ""
        meta = result[0].get("meta") or {}
        state = str(meta.get("marketState") or "").upper()
        pre = meta.get("preMarketPrice")
        if pre is not None and float(pre) > 0 and state in ("PRE", "PREPRE", "POST", "POSTPOST", ""):
            return float(pre), "pre-market"
        reg = meta.get("regularMarketPrice")
        if reg is not None and float(reg) > 0 and state == "REGULAR":
            return float(reg), "live (ref)"
        prev = meta.get("previousClose")
        if prev is not None and float(prev) > 0:
            return float(prev), "vorige slot"
        if reg is not None and float(reg) > 0:
            return float(reg), "live (ref)"
    except Exception as exc:
        logging.debug("Referentieprijs %s mislukt: %s", ticker, exc)
    return None, ""


def reference_price(ticker: str) -> Tuple[Optional[float], str]:
    now = time.monotonic()
    cached = _ref_price_cache.get(ticker.upper())
    if cached and now - cached[2] < _REF_CACHE_TTL_SEC:
        return cached[0], cached[1]
    price, label = _fetch_reference_price_yahoo(ticker.upper())
    if price is not None:
        _ref_price_cache[ticker.upper()] = (price, label, now)
    return price, label


def enrich_quotes_with_reference(rows: List[dict]) -> List[dict]:
    """Vul Last aan met slot/pre-market als er nog geen live bar is."""
    out: List[dict] = []
    for row in rows:
        r = dict(row)
        if r.get("last") is None:
            price, label = reference_price(r["ticker"])
            if price is not None:
                r["last"] = price
                r["last_label"] = label
                r["last_source"] = "ref"
        elif not r.get("last_source"):
            r["last_source"] = "live"
        out.append(r)
    return out


def apply_follow_status(rows: List[dict], follow: Dict[str, dict]) -> List[dict]:
    out: List[dict] = []
    for row in rows:
        r = dict(row)
        meta = follow.get(r["ticker"], {})
        r.update(meta)
        if not meta.get("followed", True) and r.get("status") in ("start bot", "wacht op bar"):
            r["status"] = meta.get("exclude_reason") or "niet gevolgd"
        out.append(r)
    return out


def quote_status(
    setup: Setup,
    settings: Settings,
    *,
    high: float,
    close: float,
    volume: float,
    orb_avg: Optional[float],
    orb_high: Optional[float],
    bar_num: int,
    blocked: bool = False,
) -> str:
    """Zelfde breakout-logica als trader._on_bar (incl. ORB-high en volume)."""
    if blocked:
        return "geen data"

    orb_min = settings.orb_minutes
    if orb_min > 0 and bar_num < orb_min:
        return f"ORB {bar_num}/{orb_min}"

    vol_mult = settings.volume_mult
    vol_ok = (
        orb_avg is None
        or orb_avg == 0
        or volume >= vol_mult * orb_avg
    )
    above_orb_high = orb_high is None or high >= orb_high

    if high >= setup.break_ and above_orb_high and vol_ok:
        return "breakout OK"
    if high >= setup.break_ and above_orb_high:
        return "break, vol laag"
    if high >= setup.break_ and not above_orb_high:
        return "onder ORB high"
    if close >= setup.break_ * 0.98:
        return "onder break"
    return "wacht"


def build_quote_row(
    setup: Setup,
    settings: Settings,
    *,
    close: Optional[float],
    high: Optional[float],
    volume: Optional[float],
    orb_avg: Optional[float],
    orb_high: Optional[float],
    bar_num: int,
    blocked: bool = False,
    bar_time: str = "",
) -> dict:
    if blocked or close is None or high is None or volume is None:
        return {
            "ticker": setup.ticker,
            "last": None,
            "high": None,
            "volume": None,
            "vol_need": None,
            "status": "geen data",
            "bar_time": bar_time,
            "break_": setup.break_,
        }

    vol_mult = settings.volume_mult
    vol_need = (vol_mult * orb_avg) if orb_avg and orb_avg > 0 else None
    return {
        "ticker": setup.ticker,
        "last": close,
        "high": high,
        "volume": volume,
        "vol_need": vol_need,
        "status": quote_status(
            setup,
            settings,
            high=high,
            close=close,
            volume=volume,
            orb_avg=orb_avg,
            orb_high=orb_high,
            bar_num=bar_num,
            blocked=blocked,
        ),
        "bar_time": bar_time,
        "break_": setup.break_,
    }


def placeholder_snapshots(setups: List[Setup]) -> List[dict]:
    return [
        {
            "ticker": s.ticker,
            "last": None,
            "high": None,
            "volume": None,
            "vol_need": None,
            "status": "start bot",
            "bar_time": "",
            "break_": s.break_,
            "followed": True,
            "exclude_reason": "",
            "last_source": None,
        }
        for s in setups
    ]


def _yfinance_snapshot_row(setup: Setup, settings: Settings, trade_date: date) -> dict:
    df = fetch_1m(setup.ticker, trade_date)
    if df is None:
        return build_quote_row(
            setup,
            settings,
            close=None,
            high=None,
            volume=None,
            orb_avg=None,
            orb_high=None,
            bar_num=0,
            blocked=True,
        )

    orb_min = settings.orb_minutes
    orb_vols: List[float] = []
    orb_high: Optional[float] = None

    for i, (_, row) in enumerate(df.iterrows(), start=1):
        v = float(row["Volume"])
        h = float(row["High"])
        if orb_min > 0 and i <= orb_min:
            orb_vols.append(v)
            orb_high = h if orb_high is None else max(orb_high, h)

    orb_avg = orb_avg_volume(orb_vols)
    last = df.iloc[-1]
    ts = df.index[-1]
    bar_num = len(df)

    return build_quote_row(
        setup,
        settings,
        close=float(last["Close"]),
        high=float(last["High"]),
        volume=float(last["Volume"]),
        orb_avg=orb_avg,
        orb_high=orb_high if orb_min > 0 else None,
        bar_num=bar_num,
        bar_time=ts.strftime("%H:%M"),
    )


def yfinance_snapshots(
    setups: List[Setup], settings: Settings, trade_date: date
) -> List[dict]:
    """Dashboard/backtest snapshots via yfinance (~15 min delay)."""
    key = trade_date.isoformat()
    now = time.monotonic()
    if (
        _yfinance_cache.get("key") == key
        and now - float(_yfinance_cache.get("ts", 0)) < _CACHE_TTL_SEC
        and len(_yfinance_cache.get("rows", [])) == len(setups)
    ):
        return list(_yfinance_cache["rows"])  # type: ignore[arg-type]

    rows = [_yfinance_snapshot_row(s, settings, trade_date) for s in setups]
    _yfinance_cache["key"] = key
    _yfinance_cache["ts"] = now
    _yfinance_cache["rows"] = rows
    return rows


def quote_source_hint(data_source: str, *, engine_live: bool) -> str:
    ds = data_source.lower()
    if ds == "yfinance":
        return "Snapshots: yfinance 1m (~15 min delay, dev/backtest)."
    if engine_live:
        return f"Live quotes via {ds} (zelfde bron als signalen). Vol≥ = ORB × volume_mult."
    return f"Start de bot voor live quotes via {ds}."


def live_snapshots(setups: List[Setup], settings: Settings, trade_date: date) -> List[dict]:
    """Backward-compatible alias — alleen yfinance dashboard."""
    logging.warning(
        "live_snapshots() is verouderd voor %s; gebruik trader-quotes of yfinance_snapshots.",
        settings.effective_data_source(),
    )
    return yfinance_snapshots(setups, settings, trade_date)
