"""Eenmalige backtest Krush watchlist 2026-06-03."""
from __future__ import annotations

from datetime import date

from backtest_watchlist import (
    Setup,
    fetch_intraday,
    print_comparison,
    print_scenario_report,
    run_scenario,
)

WATCHLIST = [
    Setup("DXST", 5.40, 5.82, 6.50, 7.00),
    Setup("KULR", 5.20, 5.43, 6.00, 6.50),
    Setup("DEVS", 0.66, 0.70, 0.80, 0.90),
    Setup("LASE", 3.20, 3.67, 4.40, 5.00),
    Setup("XOS", 5.00, 5.43, 7.00, 8.00),
    Setup("STAK", 2.10, 2.40, 3.00, 3.30),
    Setup("RZLT", 4.30, 4.50, 5.00, 6.00),
    Setup("TOPS", 1.50, 1.70, 2.00, 2.30),
    Setup("VRAX", 0.27, 0.30, 0.35, 0.40),
    Setup("PMI", 0.37, 0.41, 0.46, 0.55),
    Setup("PUSA", 6.40, 6.50, 7.70, 8.50),
    Setup("GNTA", 2.30, 2.58, 3.30, 4.00),
    Setup("URG", 2.10, 2.20, 2.50, 3.00),
    Setup("YMAT", 1.35, 1.45, 1.80, 2.25),
    Setup("ABTS", 2.20, 2.60, 3.20, 3.70),
    Setup("ANY", 3.90, 4.25, 5.00, 5.50),
    Setup("VSA", 4.30, 5.00, 6.50, 7.60),
    Setup("SOAR", 0.28, 0.32, 0.40, 0.50),
]

TRADE_DATE = date(2026, 6, 3)
CAPITAL = 10_000.0


def main() -> None:
    print(f"\nWatchlist backtest — {TRADE_DATE} | Cash pool: ${CAPITAL:,.0f}")
    print("Strategie: Break + 2x ORB-volume | Stop=Hold | Target=T1 | EOD 15:59 ET")
    print(f"Tickers: {len(WATCHLIST)}\nData ophalen (yfinance 1m)...")

    data = {}
    for s in WATCHLIST:
        df = fetch_intraday(s.ticker, TRADE_DATE)
        data[s.ticker] = df
        if df is not None:
            print(f"  {s.ticker:<6} {len(df):>4} candles")
        else:
            print(f"  {s.ticker:<6} GEEN DATA")

    scenarios = [
        ("A — Geen ORB (bot default)", 0),
        ("B — ORB 5 min", 5),
        ("C — ORB 15 min", 15),
    ]
    all_results = {}
    for label, orb in scenarios:
        res = run_scenario(WATCHLIST, data, label, orb, CAPITAL)
        all_results[label] = res
        print_scenario_report(res, label, CAPITAL)
    print_comparison(all_results)


if __name__ == "__main__":
    main()
