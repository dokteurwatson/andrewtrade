"""
Penny stock watchlist backtest — één trading dag, 1m candles.

Strategie:
  Entry : prijs doorbreekt Break level
          + volume op breakout candle >= 2x ORB gemiddelde
          + (scenario B/C) prijs boven Opening Range High
  Stop  : prijs raakt Hold level → exit tegen Hold
  Target: prijs raakt Target1 → exit tegen T1
  EOD   : open positie om 15:59 ET → exit tegen close

Drie scenario's:
  A — Geen ORB filter  (alleen Break + volume)
  B — ORB 5 min        (Break + vol + boven 5m high)
  C — ORB 15 min       (Break + vol + boven 15m high)

Gebruik:
    python backtest_watchlist.py [--date YYYY-MM-DD] [--capital 50]
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Optional
import warnings
warnings.filterwarnings("ignore")

import pandas as pd

from stocktrader.market_data import fetch_1m
from stocktrader.parser import Setup


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

WATCHLIST = [
    Setup("HUBC",  0.35,  0.40,  0.50,  0.60),
    Setup("ASTC",  48.00, 52.00, 60.00, 70.00),
    Setup("NAMM",  2.35,  2.49,  3.00,  4.40),
    Setup("MX",    9.30,  9.78,  11.00, 13.00),
    Setup("OLOX",  8.00,  8.70,  11.00, 12.50),
    Setup("ZENA",  1.60,  1.80,  2.00,  2.50),
    Setup("SPRC",  9.00,  10.00, 11.30, 14.00),
    Setup("UMAC",  31.00, 33.00, 40.00, 44.00),
    Setup("MASK",  3.80,  4.20,  6.75,  8.40),
    Setup("MNTS",  18.30, 20.30, 35.00, 43.50),
]


# ---------------------------------------------------------------------------
# Backtest één ticker — één scenario
# ---------------------------------------------------------------------------

@dataclass
class TradeResult:
    ticker:       str
    scenario:     str
    entry_price:  Optional[float]
    entry_time:   Optional[str]
    exit_price:   Optional[float]
    exit_time:    Optional[str]
    exit_reason:  str          # "T1", "STOP", "EOD", "NO_ENTRY", "NO_DATA", "TOO_EXPENSIVE"
    shares:       int
    capital:      float
    pnl:          float
    pnl_pct:      float
    orb_high:     Optional[float]
    breakout_vol_mult: Optional[float]


def run_scenario(
    watchlist: list[Setup],
    data: dict[str, pd.DataFrame | None],
    scenario: str,
    orb_minutes: int,
    capital: float,
) -> list[TradeResult]:
    """
    Portfolio-simulator: één cash pool voor alle tickers.
    Kapitaal zit vast zolang een trade open staat.
    Volgorde van entry bepaald door chronologische volgorde van signalen.
    """
    cash = capital

    # Per ticker: ORB stats voorberekenen
    orb_stats: dict[str, tuple[float | None, float | None]] = {}
    for setup in watchlist:
        df = data[setup.ticker]
        if df is None or orb_minutes == 0:
            orb_stats[setup.ticker] = (None, None)
        else:
            orb_df = df.iloc[:orb_minutes]
            orb_high    = float(orb_df["High"].max())   if not orb_df.empty else None
            orb_avg_vol = float(orb_df["Volume"].mean()) if not orb_df.empty else None
            orb_stats[setup.ticker] = (orb_high, orb_avg_vol)

    # Bouw één gesorteerde tijdlijn van alle candles
    all_rows: list[tuple] = []  # (timestamp, ticker, row)
    for setup in watchlist:
        df = data[setup.ticker]
        if df is None:
            continue
        scan_start = orb_minutes if orb_minutes > 0 else 0
        for ts, row in df.iloc[scan_start:].iterrows():
            all_rows.append((ts, setup.ticker, row))
    all_rows.sort(key=lambda x: x[0])

    # State per ticker
    positions: dict[str, dict] = {}   # ticker → {entry_price, entry_time, shares, spend, vol_mult}
    results_map: dict[str, TradeResult] = {}

    # Vooraf: markeer te dure en no-data tickers
    for setup in watchlist:
        shares = int(capital // setup.break_)
        if data[setup.ticker] is None:
            results_map[setup.ticker] = TradeResult(
                ticker=setup.ticker, scenario=scenario,
                entry_price=None, entry_time=None,
                exit_price=None, exit_time=None,
                exit_reason="NO_DATA", shares=0, capital=capital,
                pnl=0.0, pnl_pct=0.0, orb_high=None, breakout_vol_mult=None,
            )
        elif shares < 1:
            results_map[setup.ticker] = TradeResult(
                ticker=setup.ticker, scenario=scenario,
                entry_price=None, entry_time=None,
                exit_price=None, exit_time=None,
                exit_reason="TOO_EXPENSIVE", shares=0, capital=capital,
                pnl=0.0, pnl_pct=0.0,
                orb_high=orb_stats[setup.ticker][0], breakout_vol_mult=None,
            )

    setup_map = {s.ticker: s for s in watchlist}

    for ts, ticker, row in all_rows:
        if ticker in results_map:
            continue  # al afgehandeld (no_data / too_expensive / afgesloten)

        setup = setup_map[ticker]
        high   = float(row["High"])
        low    = float(row["Low"])
        volume = float(row["Volume"])
        orb_high, orb_avg_vol = orb_stats[ticker]

        if ticker not in positions:
            # Kan er kapitaal in?
            shares = int(cash // setup.break_)
            if shares < 1:
                continue  # wacht tot kapitaal vrijkomt

            breaks_level = high >= setup.break_
            above_orb    = (orb_high is None) or (high >= orb_high)
            vol_ok       = (orb_avg_vol is None or orb_avg_vol == 0) or (volume >= 2 * orb_avg_vol)

            if breaks_level and above_orb and vol_ok:
                spend = shares * setup.break_
                cash -= spend
                vol_mult = (volume / orb_avg_vol) if orb_avg_vol and orb_avg_vol > 0 else None
                positions[ticker] = {
                    "entry_price": setup.break_,
                    "entry_time":  ts.strftime("%H:%M"),
                    "shares":      shares,
                    "spend":       spend,
                    "vol_mult":    vol_mult,
                }
        else:
            pos = positions[ticker]

            def close_position(exit_price: float, exit_time: str, reason: str) -> None:
                nonlocal cash
                pnl = (exit_price - pos["entry_price"]) * pos["shares"]
                proceeds = exit_price * pos["shares"]
                cash += proceeds
                results_map[ticker] = TradeResult(
                    ticker=ticker, scenario=scenario,
                    entry_price=pos["entry_price"], entry_time=pos["entry_time"],
                    exit_price=exit_price, exit_time=exit_time,
                    exit_reason=reason, shares=pos["shares"], capital=pos["spend"],
                    pnl=round(pnl, 2), pnl_pct=round(pnl / pos["spend"] * 100, 1),
                    orb_high=orb_high,
                    breakout_vol_mult=round(pos["vol_mult"], 1) if pos["vol_mult"] else None,
                )
                del positions[ticker]

            if low <= setup.hold:
                close_position(setup.hold, ts.strftime("%H:%M"), "STOP")
            elif high >= setup.t1:
                close_position(setup.t1, ts.strftime("%H:%M"), "T1")

    # EOD: sluit alle open posities
    for ticker, pos in list(positions.items()):
        df = data[ticker]
        if df is not None and not df.empty:
            exit_price = float(df.iloc[-1]["Close"])
            exit_time  = df.index[-1].strftime("%H:%M")
            pnl = (exit_price - pos["entry_price"]) * pos["shares"]
            orb_high, _ = orb_stats[ticker]
            results_map[ticker] = TradeResult(
                ticker=ticker, scenario=scenario,
                entry_price=pos["entry_price"], entry_time=pos["entry_time"],
                exit_price=exit_price, exit_time=exit_time,
                exit_reason="EOD", shares=pos["shares"], capital=pos["spend"],
                pnl=round(pnl, 2), pnl_pct=round(pnl / pos["spend"] * 100, 1),
                orb_high=orb_high,
                breakout_vol_mult=round(pos["vol_mult"], 1) if pos["vol_mult"] else None,
            )

    # Tickers die nooit een signaal kregen
    for setup in watchlist:
        if setup.ticker not in results_map:
            orb_high, _ = orb_stats[setup.ticker]
            results_map[setup.ticker] = TradeResult(
                ticker=setup.ticker, scenario=scenario,
                entry_price=None, entry_time=None,
                exit_price=None, exit_time=None,
                exit_reason="NO_ENTRY", shares=0, capital=capital,
                pnl=0.0, pnl_pct=0.0, orb_high=orb_high, breakout_vol_mult=None,
            )

    return [results_map[s.ticker] for s in watchlist]


# ---------------------------------------------------------------------------
# Rapportage
# ---------------------------------------------------------------------------

ICON = {"T1": "WIN ", "STOP": "STOP", "EOD": "EOD ", "NO_ENTRY": "----", "NO_DATA": "N/A ", "TOO_EXPENSIVE": "SKIP"}

def print_scenario_report(results: list[TradeResult], scenario_label: str, capital: float) -> None:
    trades = [r for r in results if r.exit_reason not in ("NO_ENTRY", "NO_DATA", "TOO_EXPENSIVE")]
    wins   = [r for r in trades if r.exit_reason == "T1"]
    losses = [r for r in trades if r.exit_reason == "STOP"]
    total_pnl = sum(r.pnl for r in trades)

    print(f"\n{'='*65}")
    print(f"  SCENARIO {scenario_label}")
    print(f"{'='*65}")
    print(f"  {'Ticker':<6}  {'Entry':>7}  {'Exit':>7}  {'Time':>11}  {'Shares':>6}  {'PnL':>8}  {'%':>7}  Reden")
    print(f"  {'-'*60}")

    for r in results:
        icon = ICON.get(r.exit_reason, "?")
        if r.exit_reason in ("NO_ENTRY", "NO_DATA", "TOO_EXPENSIVE"):
            orb_info = f"ORB high: ${r.orb_high:.2f}" if r.orb_high else ""
            print(f"  {r.ticker:<6}  [{icon}] {r.exit_reason:<12}  {orb_info}")
        else:
            vol_str = f"vol {r.breakout_vol_mult:.1f}x" if r.breakout_vol_mult else ""
            print(
                f"  {r.ticker:<6}  ${r.entry_price:>6.2f}  ${r.exit_price:>6.2f}"
                f"  {r.entry_time}→{r.exit_time}  {r.shares:>6}x"
                f"  ${r.pnl:>+7.2f}  {r.pnl_pct:>+6.1f}%  [{icon}] {vol_str}"
            )

    print(f"  {'-'*60}")
    print(f"  Trades genomen : {len(trades)}/10  |  Wins: {len(wins)}  |  Stops: {len(losses)}")
    if trades:
        print(f"  Win rate       : {len(wins)/len(trades)*100:.0f}%")
    print(f"  Totaal PnL     : ${total_pnl:+.2f}")
    if trades:
        best  = max(trades, key=lambda r: r.pnl)
        worst = min(trades, key=lambda r: r.pnl)
        print(f"  Beste trade    : {best.ticker} ${best.pnl:+.2f} ({best.pnl_pct:+.1f}%)")
        print(f"  Slechtste      : {worst.ticker} ${worst.pnl:+.2f} ({worst.pnl_pct:+.1f}%)")


def print_comparison(all_results: dict[str, list[TradeResult]]) -> None:
    print(f"\n{'='*65}")
    print(f"  VERGELIJKING")
    print(f"{'='*65}")
    print(f"  {'Scenario':<25}  {'Trades':>7}  {'Win%':>6}  {'PnL':>9}  {'Gemist':>7}")
    print(f"  {'-'*55}")
    for label, results in all_results.items():
        trades   = [r for r in results if r.exit_reason not in ("NO_ENTRY", "NO_DATA", "TOO_EXPENSIVE")]
        wins     = [r for r in trades if r.exit_reason == "T1"]
        no_entry = [r for r in results if r.exit_reason == "NO_ENTRY"]
        total_pnl = sum(r.pnl for r in trades)
        win_pct = f"{len(wins)/len(trades)*100:.0f}%" if trades else "n/a"
        print(f"  {label:<25}  {len(trades):>7}  {win_pct:>6}  ${total_pnl:>+8.2f}  {len(no_entry):>7}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def last_trading_day() -> date:
    """Geeft de laatste werkdag terug (gisteren, of vrijdag als vandaag maandag is)."""
    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:  # zaterdag=5, zondag=6
        d -= timedelta(days=1)
    return d


def main() -> None:
    parser = argparse.ArgumentParser(description="Penny stock watchlist backtest")
    parser.add_argument("--date",    type=str,   default=None,  help="YYYY-MM-DD (default: gisteren)")
    parser.add_argument("--capital", type=float, default=50.0,  help="Kapitaal per trade in USD")
    args = parser.parse_args()

    trade_date = date.fromisoformat(args.date) if args.date else last_trading_day()
    print(f"\nWatchlist backtest — {trade_date}  |  Kapitaal per trade: ${args.capital:.0f}")
    print(f"Tickers: {', '.join(s.ticker for s in WATCHLIST)}")
    print(f"\nData ophalen...")

    data: dict[str, pd.DataFrame | None] = {}
    for setup in WATCHLIST:
        df = fetch_1m(setup.ticker, trade_date)
        data[setup.ticker] = df
        status = f"{len(df)} candles" if df is not None else "GEEN DATA"
        print(f"  {setup.ticker:<6} {status}")

    SCENARIOS = [
        ("A — Geen ORB (Break + Vol)",  0),
        ("B — ORB  5 min",              5),
        ("C — ORB 15 min",             15),
    ]

    all_results: dict[str, list[TradeResult]] = {}

    for label, orb_min in SCENARIOS:
        results = run_scenario(WATCHLIST, data, label, orb_min, args.capital)
        all_results[label] = results
        print_scenario_report(results, label, args.capital)

    print_comparison(all_results)
    print()


if __name__ == "__main__":
    main()
