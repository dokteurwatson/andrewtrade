from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from dotenv import load_dotenv

from .config import Settings, load_settings
from .exchange import Candle, ExchangeClient
from .indicators import rsi, sma


@dataclass
class FrequencyResult:
    symbol: str
    entry_count: int
    exit_count: int
    months_covered: float

    @property
    def entries_per_month(self) -> float:
        if self.months_covered <= 0:
            return 0.0
        return self.entry_count / self.months_covered

    @property
    def exits_per_month(self) -> float:
        if self.months_covered <= 0:
            return 0.0
        return self.exit_count / self.months_covered


def _months_between(start_ms: int, end_ms: int) -> float:
    if end_ms <= start_ms:
        return 0.0
    seconds = (end_ms - start_ms) / 1000
    days = seconds / 86400
    return days / 30.4375


def analyze_symbol(candles: list[Candle], settings: Settings, symbol: str) -> FrequencyResult:
    if len(candles) < max(settings.sma_period, settings.rsi_period + 1):
        return FrequencyResult(symbol=symbol, entry_count=0, exit_count=0, months_covered=0)

    in_position = False
    entry_count = 0
    exit_count = 0

    closes = [c.close for c in candles]
    warmup = max(settings.sma_period, settings.rsi_period + 1)
    for idx in range(warmup, len(candles)):
        window = closes[: idx + 1]
        current = candles[idx]
        sma_value = sma(window, settings.sma_period)
        rsi_value = rsi(window, settings.rsi_period)
        if sma_value is None or rsi_value is None:
            continue

        trend_ok = current.close > sma_value
        should_enter = trend_ok and rsi_value < settings.rsi_entry_threshold
        should_exit = rsi_value > settings.rsi_exit_threshold

        if not in_position and should_enter:
            in_position = True
            entry_count += 1
            continue

        if in_position and should_exit:
            in_position = False
            exit_count += 1

    months_covered = _months_between(candles[0].timestamp, candles[-1].timestamp)
    return FrequencyResult(
        symbol=symbol,
        entry_count=entry_count,
        exit_count=exit_count,
        months_covered=months_covered,
    )


def main() -> None:
    load_dotenv()
    settings = load_settings()
    exchange = ExchangeClient(settings.exchange_id)

    print("Trade frequency estimate")
    print(f"Exchange: {settings.exchange_id} | Timeframe: {settings.timeframe} | Candles: {settings.candle_limit}")
    print(f"Strategy: Close > SMA({settings.sma_period}) and RSI({settings.rsi_period}) < {settings.rsi_entry_threshold}")
    print(f"Exit: RSI({settings.rsi_period}) > {settings.rsi_exit_threshold}")
    print("")

    totals = defaultdict(float)
    for symbol in settings.symbols:
        candles = exchange.fetch_candles(symbol, settings.timeframe, settings.candle_limit)
        result = analyze_symbol(candles, settings, symbol)
        totals["entries"] += result.entry_count
        totals["exits"] += result.exit_count
        totals["months"] += result.months_covered

        print(
            f"{symbol}: entries={result.entry_count}, exits={result.exit_count}, "
            f"months={result.months_covered:.2f}, entries/month={result.entries_per_month:.2f}"
        )

    print("")
    if totals["months"] > 0:
        avg_entries_per_month = totals["entries"] / totals["months"]
        avg_exits_per_month = totals["exits"] / totals["months"]
    else:
        avg_entries_per_month = 0.0
        avg_exits_per_month = 0.0

    now = datetime.now(timezone.utc).isoformat()
    print(f"Generated at: {now}")
    print(f"Portfolio total entries: {int(totals['entries'])}")
    print(f"Portfolio total exits: {int(totals['exits'])}")
    print(f"Portfolio average entries/month (aggregated): {avg_entries_per_month:.2f}")
    print(f"Portfolio average exits/month (aggregated): {avg_exits_per_month:.2f}")


if __name__ == "__main__":
    main()
