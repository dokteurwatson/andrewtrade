"""
Backtest laatste N minuten — zelfde entry-logica als stocktrader.trader._on_bar.

Geen ORB-high filter (alleen volume vs ORB-gemiddelde + break level).

Gebruik:
  python backtest_recent_window.py --minutes 20
  python backtest_recent_window.py --minutes 20 --stream-from 12:51
  python backtest_recent_window.py --date 2026-06-04 --minutes 20 --capital 105.63
"""
from __future__ import annotations

import argparse
import os
import warnings
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore")

import pandas as pd

from stocktrader.market_data import ET, fetch_1m, orb_avg_volume
from stocktrader.parser import Setup, parse_watchlist

WATCHLIST_TEXT = """
XOS 	$6.30 	$7.00 	$8.00 	$10.00
STAK 	$3.50 	$3.90 	$4.50 	$5.00
SBEV 	$0.34 	$0.39 	$0.45 	$0.50
FOXX 	$4.40 	$4.80 	$6.00 	$8.00
TWAV 	$2.20 	$2.60 	$3.00 	$4.00
YYGH 	$0.20 	$0.22 	$0.25 	$0.30
SDOT 	$6.40 	$7.00 	$8.50 	$9.50
BNRG 	$1.80 	$2.00 	$2.70 	$3.50
FOFO 	$6.00 	$7.20 	$8.00 	$9.50
CXAI 	$0.25 	$0.28 	$0.33 	$0.40
VGNT 	$48.00 	$49.92 	$55.00 	$60.00
TURB 	$1.70 	$1.90 	$2.20 	$2.50
RZLT 	$4.50 	$4.64 	$5.30 	$6.00
DRTS 	$10.80 	$11.00 	$12.00 	$15.00
SELX 	$0.56 	$0.65 	$0.80 	$0.90
WCT 	$2.80 	$3.00 	$3.50 	$4.00
PMI 	$0.29 	$0.33 	$0.39 	$0.46
"""


@dataclass
class BarSignal:
    ticker: str
    bar_time: str
    high: float
    volume: float
    break_: float
    orb_avg: Optional[float]
    vol_mult: float
    vol_ok: bool
    breaks: bool
    would_enter: bool
    block_reason: str


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def simulate_ticker(
    setup: Setup,
    df: pd.DataFrame,
    *,
    window_start: datetime,
    window_end: datetime,
    stream_from: Optional[time],
    orb_minutes: int,
    volume_mult: float,
    cash: float,
) -> tuple[List[BarSignal], Optional[str]]:
    """Loop alle bars; rapporteer signalen in [window_start, window_end]."""
    if stream_from:
        stream_dt = datetime.combine(window_start.date(), stream_from, tzinfo=ET)
        df = df[df.index >= stream_dt]
    if df.empty:
        return [], "NO_DATA"

    bar_count = 0
    orb_volumes: List[float] = []
    signals: List[BarSignal] = []
    sizing_note: Optional[str] = None

    for ts, row in df.iterrows():
        bar_count += 1
        high = float(row["High"])
        volume = float(row["Volume"])

        if orb_minutes > 0 and bar_count <= orb_minutes:
            orb_volumes.append(volume)
            continue

        orb_avg = orb_avg_volume(orb_volumes)
        vol_ok = (
            orb_avg is None
            or orb_avg == 0
            or volume >= volume_mult * orb_avg
        )
        breaks = high >= setup.break_
        would_enter = breaks and vol_ok

        if ts < window_start or ts > window_end:
            continue

        block = ""
        if not breaks:
            block = "geen breakout (high < break)"
        elif not vol_ok:
            block = f"volume te laag ({volume:.0f} < {volume_mult:.1f}x {orb_avg:.0f})"
        else:
            shares = int(cash * 0.98 // setup.break_)
            if shares < 1:
                block = f"onvoldoende cash (~{cash:.2f} voor break ${setup.break_:.2f})"
                would_enter = False
            elif sizing_note is None:
                sizing_note = f"{shares} shares @ break"

        signals.append(
            BarSignal(
                ticker=setup.ticker,
                bar_time=ts.strftime("%H:%M"),
                high=high,
                volume=volume,
                break_=setup.break_,
                orb_avg=orb_avg,
                vol_mult=volume_mult,
                vol_ok=vol_ok,
                breaks=breaks,
                would_enter=would_enter and not block,
                block_reason=block or "ENTRY",
            )
        )

    return signals, sizing_note


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest laatste N minuten (bot-logica)")
    p.add_argument("--minutes", type=int, default=20)
    p.add_argument("--window-end", type=str, default="",
                   help="Einde venster HH:MM ET (default: nu in ET)")
    p.add_argument("--date", type=str, default="")
    p.add_argument("--stream-from", type=str, default="",
                   help="Simuleer late bot-start (HH:MM ET), ORB vanaf dit moment")
    p.add_argument("--capital", type=float, default=105.63,
                   help="Sizing cash (EUR/USD bot wallet)")
    p.add_argument("--orb-minutes", type=int, default=None)
    p.add_argument("--volume-mult", type=float, default=None)
    args = p.parse_args()

    orb_minutes = args.orb_minutes if args.orb_minutes is not None else _env_int("ORB_MINUTES", 0)
    volume_mult = args.volume_mult if args.volume_mult is not None else _env_float("VOLUME_MULT", 2.0)

    trade_date = date.fromisoformat(args.date) if args.date else datetime.now(ET).date()
    if args.window_end:
        h, m = args.window_end.split(":")
        window_end = datetime.combine(trade_date, time(int(h), int(m)), tzinfo=ET)
    else:
        window_end = datetime.now(ET)
    window_start = window_end - timedelta(minutes=args.minutes)

    stream_from: Optional[time] = None
    if args.stream_from:
        h, m = args.stream_from.split(":")
        stream_from = time(int(h), int(m))

    setups = parse_watchlist(WATCHLIST_TEXT)
    if not setups:
        raise SystemExit("Watchlist parse mislukt")

    print(f"Datum {trade_date} ET | venster {window_start.strftime('%H:%M')}–{window_end.strftime('%H:%M')}")
    print(f"ORB_MINUTES={orb_minutes} VOLUME_MULT={volume_mult} cash={args.capital:.2f}")
    if stream_from:
        print(f"Stream start (bot late): {stream_from.strftime('%H:%M')} ET")
    print(f"Tickers: {len(setups)}\n")

    any_entry = False
    for setup in setups:
        df = fetch_1m(setup.ticker, trade_date)
        if df is None:
            print(f"{setup.ticker:6}  GEEN DATA (yfinance)")
            continue

        sigs, sizing = simulate_ticker(
            setup, df,
            window_start=window_start,
            window_end=window_end,
            stream_from=stream_from,
            orb_minutes=orb_minutes,
            volume_mult=volume_mult,
            cash=args.capital,
        )

        entries = [s for s in sigs if s.would_enter]
        break_blocked = [s for s in sigs if s.breaks and not s.would_enter]

        if entries:
            any_entry = True
            s = entries[0]
            orb_s = f"{s.orb_avg:.0f}" if s.orb_avg else "n/a"
            extra = f" (+{len(entries) - 1} meer)" if len(entries) > 1 else ""
            print(
                f"{s.ticker:6}  ENTRY {s.bar_time}{extra}  high=${s.high:.4f} >= break=${s.break_:.2f}  "
                f"vol={s.volume:.0f} (orb_avg={orb_s}, need>={s.vol_mult}x)  sizing: {sizing}"
            )
        elif break_blocked:
            s = break_blocked[0]
            print(
                f"{setup.ticker:6}  BREAKOUT maar geblokkeerd @ {s.bar_time}: {s.block_reason}"
            )
        elif sigs:
            s = max(sigs, key=lambda x: x.high)
            print(
                f"{setup.ticker:6}  geen entry | max high ${s.high:.4f} vs break ${s.break_:.2f} @ {s.bar_time}"
            )
        else:
            last = df.iloc[-1]
            print(
                f"{setup.ticker:6}  geen bar in venster | laatste ${float(last['Close']):.4f} @ "
                f"{df.index[-1].strftime('%H:%M')}"
            )

    print()
    if not any_entry:
        print("Geen ENTRY-signalen in dit venster met bot-regels.")
        print("(Live bot deed niets als trader niet gestart was — zie logs zonder 'Stocktrader gestart'.)")
    else:
        print("Minstens één ticker had een ENTRY in dit venster — bot had moeten handelen als ACTIEF + stream.")


if __name__ == "__main__":
    main()
