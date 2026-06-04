"""Per-ticker backtest — 2026-06-03, scenario A, $1000 per ticker."""
from datetime import date

from backtest_watchlist import Setup, fetch_intraday, run_scenario
from backtest_jun03 import WATCHLIST, TRADE_DATE

CAPITAL = 1000.0


def main() -> None:
    print(f"Per-ticker | {TRADE_DATE} | Scenario A | ${CAPITAL:.0f}/ticker\n")
    print(f"{'Ticker':<6} {'Reden':<12} {'Entry':>7} {'Exit':>7} {'PnL':>9} {'%':>7}  vol")
    print("-" * 58)

    total = 0.0
    trades = wins = stops = 0

    for s in WATCHLIST:
        df = fetch_intraday(s.ticker, TRADE_DATE)
        r = run_scenario([s], {s.ticker: df}, "A", 0, CAPITAL)[0]
        total += r.pnl
        if r.exit_reason not in ("NO_ENTRY", "NO_DATA", "TOO_EXPENSIVE"):
            trades += 1
            if r.exit_reason == "T1":
                wins += 1
            elif r.exit_reason == "STOP":
                stops += 1

        ep = f"{r.entry_price:.2f}" if r.entry_price else "-"
        xp = f"{r.exit_price:.2f}" if r.exit_price else "-"
        vm = f"{r.breakout_vol_mult:.1f}x" if r.breakout_vol_mult else ""
        print(
            f"{s.ticker:<6} {r.exit_reason:<12} {ep:>7} {xp:>7} "
            f"{r.pnl:>+9.2f} {r.pnl_pct:>+6.1f}%  {vm}"
        )

    print("-" * 58)
    print(f"Trades: {trades}/18 | T1: {wins} | STOP: {stops} | Totaal PnL: ${total:+.2f}")


if __name__ == "__main__":
    main()
