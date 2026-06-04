"""
Live market snapshot voor dashboard (yfinance 1m, ~15 min delay).

Toont laatste bar: prijs vs break en volume vs ORB-target (zelfde formule als trader).
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Dict, List, Optional

from .config import Settings
from .market_data import ET, fetch_1m, orb_avg_volume
from .parser import Setup

_CACHE_TTL_SEC = 55
_cache: Dict[str, object] = {"ts": 0.0, "rows": []}


def _snapshot_row(setup: Setup, settings: Settings, trade_date: date) -> dict:
    df = fetch_1m(setup.ticker, trade_date)
    if df is None:
        return {
            "ticker": setup.ticker,
            "last": None,
            "high": None,
            "volume": None,
            "vol_need": None,
            "status": "geen data",
            "bar_time": "",
        }

    orb_min = settings.orb_minutes
    vol_mult = settings.volume_mult
    orb_vols: List[float] = []

    for i, (_, row) in enumerate(df.iterrows(), start=1):
        v = float(row["Volume"])
        if orb_min > 0 and i <= orb_min:
            orb_vols.append(v)

    orb_avg = orb_avg_volume(orb_vols)

    last = df.iloc[-1]
    ts = df.index[-1]
    high = float(last["High"])
    close = float(last["Close"])
    volume = float(last["Volume"])
    vol_need = (vol_mult * orb_avg) if orb_avg and orb_avg > 0 else None
    vol_ok = vol_need is None or volume >= vol_need
    breaks = high >= setup.break_

    if breaks and vol_ok:
        status = "breakout OK"
    elif breaks:
        status = "break, vol laag"
    elif close >= setup.break_ * 0.98:
        status = "onder break"
    else:
        status = "wacht"

    return {
        "ticker": setup.ticker,
        "last": close,
        "high": high,
        "volume": volume,
        "vol_need": vol_need,
        "status": status,
        "bar_time": ts.strftime("%H:%M"),
        "break_": setup.break_,
    }


def live_snapshots(setups: List[Setup], settings: Settings, trade_date: date) -> List[dict]:
    """Gecachte rijen voor dashboard; ververst elke ~55s."""
    key = trade_date.isoformat()
    now = time.monotonic()
    if (
        _cache.get("key") == key
        and now - float(_cache.get("ts", 0)) < _CACHE_TTL_SEC
        and len(_cache.get("rows", [])) == len(setups)
    ):
        return list(_cache["rows"])  # type: ignore[arg-type]

    rows = [_snapshot_row(s, settings, trade_date) for s in setups]
    _cache["key"] = key
    _cache["ts"] = now
    _cache["rows"] = rows
    return rows
