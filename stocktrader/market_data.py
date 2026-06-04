"""
Gedeelde marktdata-hulpfuncties (yfinance 1m, ORB-volume).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time as dt_time, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ET = ZoneInfo("America/New_York")


def fetch_1m(ticker: str, trade_date: date) -> Optional[pd.DataFrame]:
    """1m candles voor één handelsdag, ET-sessie 09:30–15:59."""
    start = datetime.combine(trade_date, dt_time.min)
    end = start + timedelta(days=1)
    try:
        df = yf.download(
            ticker,
            start=start,
            end=end,
            interval="1m",
            progress=False,
            auto_adjust=True,
        )
    except Exception as exc:
        logging.debug("fetch_1m %s: %s", ticker, exc)
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC").tz_convert(ET)
    else:
        df.index = df.index.tz_convert(ET)
    df = df.between_time("09:30", "15:59")
    return df if not df.empty else None


def orb_avg_volume(volumes: List[float]) -> Optional[float]:
    """Gemiddeld volume over ORB-bars; None als lijst leeg is."""
    if not volumes:
        return None
    return sum(volumes) / len(volumes)
