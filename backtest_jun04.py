"""
Backtest Krush watchlist 04-06-2026.
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
import warnings
warnings.filterwarnings("ignore")

from stocktrader.parser import Setup
from backtest_watchlist import run_scenario, print_scenario_report, print_comparison, fetch_1m
from datetime import date

WATCHLIST = [
    # Top Picks
    Setup("XOS",   6.30,  7.00,  8.00,  10.00),
    Setup("STAK",  3.50,  3.90,  4.50,   5.00),
    Setup("SBEV",  0.34,  0.39,  0.45,   0.50),
    # Other Picks
    Setup("FOXX",  4.40,  4.80,  6.00,   8.00),
    Setup("TWAV",  2.20,  2.60,  3.00,   4.00),
    Setup("YYGH",  0.20,  0.22,  0.25,   0.30),
    Setup("SDOT",  6.40,  7.00,  8.50,   9.50),
    Setup("BNRG",  1.80,  2.00,  2.70,   3.50),
    Setup("FOFO",  6.00,  7.20,  8.00,   9.50),
    Setup("CXAI",  0.25,  0.28,  0.33,   0.40),
    Setup("VGNT", 48.00, 49.92, 55.00,  60.00),
    Setup("TURB",  1.70,  1.90,  2.20,   2.50),
    Setup("RZLT",  4.50,  4.64,  5.30,   6.00),
    Setup("DRTS", 10.80, 11.00, 12.00,  15.00),
    Setup("SELX",  0.56,  0.65,  0.80,   0.90),
    Setup("WCT",   2.80,  3.00,  3.50,   4.00),
    Setup("PMI",   0.29,  0.33,  0.39,   0.46),
]

CAPITAL = 50.0
FEE_PCT = 0.0015   # T212 valutaconversie 0.15% per zijde (0.30% round-trip)
TRADE_DATE = date(2026, 6, 4)

print(f"\nBacktest Krush watchlist — {TRADE_DATE}  |  Kapitaal: ${CAPITAL:.0f}  |  Fee: {FEE_PCT*100:.2f}% p/zijde")
print(f"Tickers: {', '.join(s.ticker for s in WATCHLIST)}\n")
print("Data ophalen via yfinance...")

data = {}
for s in WATCHLIST:
    df = fetch_1m(s.ticker, TRADE_DATE)
    data[s.ticker] = df
    status = f"{len(df)} candles" if df is not None else "GEEN DATA"
    print(f"  {s.ticker:<6} {status}")

SCENARIOS = [
    ("A — Geen ORB (Break + Vol)",  0),
    ("B — ORB  5 min",              5),
    ("C — ORB 15 min",             15),
]

all_results = {}
for label, orb_min in SCENARIOS:
    results = run_scenario(WATCHLIST, data, label, orb_min, CAPITAL, FEE_PCT)
    all_results[label] = results
    print_scenario_report(results, label, CAPITAL)

print_comparison(all_results)
print()
