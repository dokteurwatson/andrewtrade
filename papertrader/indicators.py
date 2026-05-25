from __future__ import annotations

from typing import Iterable, List


def sma(values: Iterable[float], period: int) -> float | None:
    data = list(values)
    if len(data) < period or period <= 0:
        return None
    window = data[-period:]
    return sum(window) / period


def rsi(values: Iterable[float], period: int) -> float | None:
    data = list(values)
    if period <= 0 or len(data) < period + 1:
        return None

    gains: List[float] = []
    losses: List[float] = []
    for idx in range(len(data) - period, len(data)):
        diff = data[idx] - data[idx - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
