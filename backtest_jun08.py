"""
Backtest Krush watchlist 08-06-2026.

Live bot volgt alleen GMHS, GLXG, LASE (ORB=0, T2-runner).
BGMS / NEXR / ELOG / STI staan in de volledige lijst voor referentie.

Gebruik (vanavond, na sluiting US-markt):
    python backtest_jun08.py
    python backtest_jun08.py --capital 100
"""
from __future__ import annotations

import argparse
import io
import sys
import warnings

warnings.filterwarnings("ignore")

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from datetime import date

from stocktrader.market_data import fetch_1m
from stocktrader.parser import Setup
from backtest_watchlist import (
    print_comparison,
    print_scenario_report,
    run_scenario,
)

TRADE_DATE = date(2026, 6, 8)
FEE_PCT = 0.0015  # T212 0.15% per zijde

# Hold | Break | T1 | T2
WATCHLIST_FULL = [
    Setup("BGMS",  1.70,  2.10,  2.50,  3.00),  # geen Finazon
    Setup("GMHS",  1.93,  2.11,  2.60,  3.60),
    Setup("NEXR",  1.85,  2.11,  2.80,  3.30),  # geen Finazon
    Setup("ELOG",  1.60,  1.85,  2.20,  2.50),  # niet op T212
    Setup("GLXG",  1.90,  2.47,  2.80,  3.00),
    Setup("LASE",  2.80,  3.00,  4.20,  6.00),  # live breakout OK
    Setup("STI",  36.00, 42.00, 50.00, 58.00),  # close-only op T212
]

WATCHLIST_TRADABLE = [
    Setup("GMHS",  1.93,  2.11,  2.60,  3.60),
    Setup("GLXG",  1.90,  2.47,  2.80,  3.00),
    Setup("LASE",  2.80,  3.00,  4.20,  6.00),
]

SCENARIOS = [
    ("A — Geen ORB (Break + Vol)",  0),
    ("B — ORB  5 min",              5),
    ("C — ORB 15 min",             15),
]


def fetch_data(watchlist: list[Setup]) -> dict:
    data = {}
    print("Data ophalen via yfinance 1m...")
    for s in watchlist:
        df = fetch_1m(s.ticker, TRADE_DATE)
        data[s.ticker] = df
        if df is None:
            status = "GEEN DATA"
        else:
            first = df.index[0].strftime("%H:%M")
            last = df.index[-1].strftime("%H:%M")
            status = f"{len(df)} candles ({first}–{last})"
        print(f"  {s.ticker:<6} {status}")
    print()
    return data


def run_block(
    title: str,
    watchlist: list[Setup],
    data: dict,
    capital: float,
    *,
    scenarios: list[tuple[str, int]] | None = None,
    t2_runner: bool = True,
) -> None:
    print(f"\n{'#' * 65}")
    print(f"  {title}")
    print(f"  Datum: {TRADE_DATE}  |  Kapitaal: ${capital:.0f}  |  "
          f"{'T2-runner' if t2_runner else 'T1-only'}")
    print(f"  Tickers: {', '.join(s.ticker for s in watchlist)}")
    print(f"{'#' * 65}")

    orb_scenarios = scenarios if scenarios is not None else [SCENARIOS[0]]
    all_results: dict[str, list] = {}
    for label, orb_min in orb_scenarios:
        results = run_scenario(
            watchlist, data, label, orb_min, capital, FEE_PCT, t2_runner=t2_runner,
        )
        all_results[label] = results
        print_scenario_report(results, label, capital)

    if len(orb_scenarios) > 1:
        print_comparison(all_results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Krush watchlist 08-06-2026")
    parser.add_argument("--capital", type=float, default=50.0, help="Startkapitaal USD")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Ook volledige watchlist + ORB 5/15 scenario's draaien",
    )
    args = parser.parse_args()

    print(
        f"\nBacktest Krush — {TRADE_DATE}  |  Kapitaal: ${args.capital:.0f}  |  "
        f"Fee: {FEE_PCT * 100:.2f}% p/zijde"
    )

    tradable_data = fetch_data(WATCHLIST_TRADABLE)

    run_block(
        "LIVE-MATCH — tradable tickers, ORB=0, T2-runner",
        WATCHLIST_TRADABLE,
        tradable_data,
        args.capital,
        scenarios=[SCENARIOS[0]],
        t2_runner=True,
    )

    print(f"\n{'=' * 65}")
    print("  T1-only vs T2-runner (tradable, ORB=0)")
    print(f"{'=' * 65}")
    for mode, t2 in [("T1-only", False), ("T2-runner", True)]:
        results = run_scenario(
            WATCHLIST_TRADABLE, tradable_data, mode, 0, args.capital, FEE_PCT,
            t2_runner=t2,
        )
        trades = [r for r in results if r.exit_reason not in ("NO_ENTRY", "NO_DATA", "TOO_EXPENSIVE")]
        pnl = sum(r.pnl for r in trades)
        wins = sum(1 for r in trades if r.exit_reason in ("T1", "T2"))
        print(f"  {mode:<12}  trades={len(trades)}  wins={wins}  PnL=${pnl:+.2f}")

    if args.full:
        full_data = fetch_data(WATCHLIST_FULL)
        run_block(
            "VOLLEDIGE WATCHLIST — alle scenario's A/B/C, T2-runner",
            WATCHLIST_FULL,
            full_data,
            args.capital,
            scenarios=SCENARIOS,
            t2_runner=True,
        )

    print()


if __name__ == "__main__":
    main()
