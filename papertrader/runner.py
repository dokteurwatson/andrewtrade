from __future__ import annotations

import logging
import time
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

from .config import Settings, load_settings
from .exchange import Candle, ExchangeClient
from .indicators import rsi, sma
from .notifier import TelegramNotifier
from .state import BotState, Position, StateStore, calculate_total_equity, utc_day_key


@dataclass
class Signal:
    symbol: str
    candle: Candle
    sma_value: float | None
    rsi_value: float | None
    trend_ok: bool
    enter_long: bool
    exit_long: bool


class PaperTrader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.exchange = ExchangeClient(settings.exchange_id)
        self.store = StateStore(settings.state_dir, settings.start_capital_usd)
        self.state = self.store.load()
        self.notifier = TelegramNotifier(settings.telegram_enabled, settings.telegram_bot_token, settings.telegram_chat_id)
        self.trades_log_path = Path(settings.state_dir) / "trades.jsonl"

    def run_forever(self) -> None:
        logging.info("Paper trader started on %s %s for %s", self.settings.exchange_id, self.settings.timeframe, self.settings.symbols)
        self._send_startup_message()
        while True:
            try:
                self._run_cycle()
            except Exception as exc:
                logging.exception("Cycle failed: %s", exc)
                self.notifier.send(f"PaperTrader error: {exc}")
            time.sleep(self.settings.poll_seconds)

    def _run_cycle(self) -> None:
        logging.info("Starting cycle for %s", self.settings.symbols)
        symbols = self.settings.symbols
        candles_by_symbol: Dict[str, List[Candle]] = {
            symbol: self.exchange.fetch_candles(symbol, self.settings.timeframe, self.settings.candle_limit) for symbol in symbols
        }
        last_prices = {symbol: candles[-1].close for symbol, candles in candles_by_symbol.items() if candles}
        now = datetime.now(timezone.utc)

        self._roll_daily_state_if_needed(now, last_prices)
        if self.state.cooldown_remaining > 0:
            new_candle_seen = any(
                candles and self.state.last_candle_ts.get(symbol) != candles[-1].timestamp
                for symbol, candles in candles_by_symbol.items()
            )
            if new_candle_seen:
                self.state.cooldown_remaining -= 1

        for symbol, candles in candles_by_symbol.items():
            if len(candles) < max(self.settings.sma_period, self.settings.rsi_period + 1):
                continue

            latest = candles[-1]
            if self.state.last_candle_ts.get(symbol) == latest.timestamp:
                continue

            signal = self._build_signal(symbol, candles)
            self._evaluate_exits(signal)
            self._evaluate_entries(signal, last_prices)
            self.state.last_candle_ts[symbol] = latest.timestamp

        self.store.save(self.state)

    def _build_signal(self, symbol: str, candles: List[Candle]) -> Signal:
        closes = [c.close for c in candles]
        sma_value = sma(closes, self.settings.sma_period)
        rsi_value = rsi(closes, self.settings.rsi_period)
        latest = candles[-1]
        trend_ok = sma_value is not None and latest.close > sma_value
        enter_long = trend_ok and rsi_value is not None and rsi_value < self.settings.rsi_entry_threshold
        exit_long = rsi_value is not None and rsi_value > self.settings.rsi_exit_threshold
        return Signal(
            symbol=symbol,
            candle=latest,
            sma_value=sma_value,
            rsi_value=rsi_value,
            trend_ok=trend_ok,
            enter_long=enter_long,
            exit_long=exit_long,
        )

    def _evaluate_entries(self, signal: Signal, last_prices: Dict[str, float]) -> None:
        if signal.symbol in self.state.positions:
            return
        if not signal.enter_long:
            return
        if self.state.cooldown_remaining > 0:
            return

        equity = calculate_total_equity(self.state.cash_usd, self.state.positions, last_prices)
        reserve = self.state.cash_usd * self.settings.cash_reserve_pct
        spendable_cash = self.state.cash_usd - reserve
        if spendable_cash < self.settings.min_order_usd:
            return
        above_threshold = equity >= self.settings.risk_threshold_balance
        if above_threshold:
            if len(self.state.positions) >= self.settings.max_open_positions_above_threshold:
                return
            if self._daily_loss_exceeded(equity):
                return
            position_usd = self._calc_risk_based_position_usd(equity)
        else:
            if self.settings.position_sizing_below_threshold == "all_in":
                position_usd = spendable_cash
            else:
                position_usd = self._calc_risk_based_position_usd(equity)

        if position_usd < self.settings.min_order_usd:
            return

        entry_price = signal.candle.close * (1 + self.settings.slippage_rate)
        quantity = position_usd / entry_price
        gross_cost = quantity * entry_price
        fee = gross_cost * self.settings.taker_fee_rate
        total_cost = gross_cost + fee

        if total_cost > spendable_cash:
            quantity = spendable_cash / (entry_price * (1 + self.settings.taker_fee_rate))
            gross_cost = quantity * entry_price
            fee = gross_cost * self.settings.taker_fee_rate
            total_cost = gross_cost + fee

        if quantity <= 0:
            return

        if above_threshold:
            stop_price = entry_price * (1 - self.settings.stop_loss_pct_above_threshold)
        else:
            stop_price = 0.0

        self.state.cash_usd -= total_cost
        self.state.positions[signal.symbol] = Position(
            symbol=signal.symbol,
            quantity=quantity,
            entry_price=entry_price,
            entry_timestamp=signal.candle.timestamp,
            stop_price=stop_price,
        )

        message = (
            f"LETS GOOO. AndrewTrade just LOADED UP on {signal.symbol}. "
            f"Bought {quantity:.6f} units at ${entry_price:.4f} like a KING. "
            f"RSI was crying at {signal.rsi_value:.2f} — we bought the fear. "
            f"SMA says ${signal.sma_value:.4f}, we are ABOVE it. "
            f"Fee paid to the exchange peasants: ${fee:.4f}. Cash left: ${self.state.cash_usd:.2f}. "
            f"The broke stay broke. We move."
        )
        logging.info(message)
        self.notifier.send(message)
        self._append_trade_log(
            {
                "type": "ENTRY",
                "symbol": signal.symbol,
                "timestamp": signal.candle.timestamp,
                "price": entry_price,
                "quantity": quantity,
                "fee": fee,
                "cash_after": self.state.cash_usd,
            }
        )

    def _evaluate_exits(self, signal: Signal) -> None:
        position = self.state.positions.get(signal.symbol)
        if not position:
            return

        price_raw = signal.candle.close
        stop_hit = position.stop_price > 0 and signal.candle.low <= position.stop_price
        reason = "RSI_EXIT" if signal.exit_long else "STOP_LOSS" if stop_hit else ""
        if not reason:
            return

        exit_price = position.stop_price if stop_hit else price_raw
        exit_price = exit_price * (1 - self.settings.slippage_rate)
        proceeds = position.quantity * exit_price
        fee = proceeds * self.settings.taker_fee_rate
        net_proceeds = proceeds - fee
        pnl = (exit_price - position.entry_price) * position.quantity - (position.entry_price * position.quantity * self.settings.taker_fee_rate) - fee

        self.state.cash_usd += net_proceeds
        del self.state.positions[signal.symbol]

        equity_after_exit = self.state.cash_usd
        above_threshold = equity_after_exit >= self.settings.risk_threshold_balance
        if above_threshold:
            if pnl < 0:
                self.state.consecutive_losses += 1
            else:
                self.state.consecutive_losses = 0

            if self.state.consecutive_losses >= self.settings.max_consecutive_losses_above_threshold:
                self.state.cooldown_remaining = self.settings.cooldown_candles_after_limit
                self.state.consecutive_losses = 0
        else:
            self.state.consecutive_losses = 0
            self.state.cooldown_remaining = 0

        if pnl >= 0:
            message = (
                f"CASHED OUT. AndrewTrade just SOLD {position.symbol} for a W. "
                f"Sold {position.quantity:.6f} at ${exit_price:.4f}. "
                f"Profit: +${pnl:.4f}. Reason: {reason}. "
                f"Top G mentality — we don't hold bags, we hold GAINS. "
                f"Cash balance: ${self.state.cash_usd:.2f}."
            )
        else:
            message = (
                f"We take the L with DIGNITY. {position.symbol} sold at ${exit_price:.4f}. "
                f"Loss: ${pnl:.4f}. Reason: {reason}. "
                f"Even Top G loses a battle — never the war. "
                f"Stop-loss is not weakness, it is DISCIPLINE. Cash: ${self.state.cash_usd:.2f}."
            )
        logging.info(message)
        self.notifier.send(message)
        self._append_trade_log(
            {
                "type": "EXIT",
                "symbol": signal.symbol,
                "timestamp": signal.candle.timestamp,
                "price": exit_price,
                "quantity": position.quantity,
                "fee": fee,
                "pnl": pnl,
                "cash_after": self.state.cash_usd,
                "reason": reason,
            }
        )

        if pnl > 0:
            bugatti_message = self._build_bugatti_message()
            logging.info(bugatti_message)
            self.notifier.send(bugatti_message)

    def _roll_daily_state_if_needed(self, now: datetime, last_prices: Dict[str, float]) -> None:
        day_key = utc_day_key(now)
        if self.state.day_key == day_key:
            return
        self.state.day_key = day_key
        equity = calculate_total_equity(self.state.cash_usd, self.state.positions, last_prices)
        self.state.day_start_equity = equity

    def _daily_loss_exceeded(self, equity: float) -> bool:
        if self.state.day_start_equity <= 0:
            return False
        daily_drawdown = max(0.0, (self.state.day_start_equity - equity) / self.state.day_start_equity)
        return daily_drawdown >= self.settings.max_daily_loss_above_threshold

    def _calc_risk_based_position_usd(self, equity: float) -> float:
        risk_budget = equity * self.settings.risk_per_trade_above_threshold
        stop_pct = self.settings.stop_loss_pct_above_threshold
        if stop_pct <= 0:
            return 0.0
        position = risk_budget / stop_pct
        return min(position, self.state.cash_usd)

    def _append_trade_log(self, payload: Dict[str, float | str | int]) -> None:
        self.trades_log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload) + "\n"
        with self.trades_log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def _send_startup_message(self) -> None:
        state_mode = "ABOVE_THRESHOLD" if self.state.cash_usd >= self.settings.risk_threshold_balance else "BELOW_THRESHOLD"
        mode_label = "PAPER TRADING (simulated)" if self.settings.mode == "paper" else "LIVE TRADING (REAL MONEY)"
        message = (
            f"WAKEY WAKEY, the matrix is open for business. AndrewTrade is ONLINE. "
            f"MODE: {mode_label}. "
            f"We are trading {', '.join(self.settings.coin_list)} on {self.settings.exchange_id.upper()} "
            f"with ${self.state.cash_usd:.2f} in the war chest. "
            f"Timeframe: {self.settings.timeframe}. Risk mode: {state_mode}. "
            f"The weak paper-hand peasants sleep — we GRIND. Let's get this bread."
        )
        self.notifier.send(message)

    def _build_bugatti_message(self) -> str:
        current_equity = self.state.cash_usd
        if self.settings.bugatti_target_usd <= 0:
            return "Profit secured. Bugatti mode disabled (invalid target)."

        progress = (current_equity / self.settings.bugatti_target_usd) * 100
        progress = max(0.0, min(progress, 100.0))

        if progress < 1:
            vibe = "Start your engines. We just left the pit lane."
        elif progress < 10:
            vibe = "Turbo warm-up. Green candles are fueling the dream."
        elif progress < 50:
            vibe = "Mid-race grind. Bugatti radar is officially online."
        elif progress < 100:
            vibe = "Final lap energy. Tell the valet to stay ready."
        else:
            vibe = "Garage unlocked. Time to spec the color."

        return f"Bugatti Progress: {progress:.4f}% | {vibe}"


def main() -> None:
    load_dotenv()
    settings = load_settings()
    resolved_level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(level=resolved_level, format="%(asctime)s | %(levelname)s | %(message)s")
    if settings.mode != "paper":
        raise RuntimeError("Only MODE=paper is currently supported")
    bot = PaperTrader(settings)
    bot.run_forever()


if __name__ == "__main__":
    main()
