"""
Trailing stop-loss — percentage onder high water mark of vaste winst-stappen.
"""
from __future__ import annotations

import functools
from typing import List, Tuple

from .config import Settings


@functools.lru_cache(maxsize=32)
def parse_trail_steps(raw: str) -> List[Tuple[float, float]]:
    """Parse TRAIL_STEPS zoals '5:0,10:5,15:10' → [(5, 0), (10, 5), (15, 10)]."""
    steps: List[Tuple[float, float]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        gain_s, stop_s = part.split(":", 1)
        try:
            steps.append((float(gain_s.strip()), float(stop_s.strip())))
        except ValueError:
            continue
    steps.sort(key=lambda x: x[0])
    return steps


def trailing_allowed(pos: dict) -> bool:
    """Trailing mag zolang de T2-runner nog niet actief is."""
    return not pos.get("runner_active", False)


def compute_trailing_stop(
    *,
    entry: float,
    high_water: float,
    current_stop: float,
    target: float,
    settings: Settings,
) -> Tuple[float, float, bool]:
    """
    Bereken nieuwe high_water en stop.

    Returns (new_high_water, new_stop, changed).
    """
    if not settings.trailing_stop_enabled or entry <= 0:
        return high_water, current_stop, False

    hw = max(high_water, entry)
    gain_pct = (hw - entry) / entry * 100.0
    if gain_pct < settings.trail_activation_pct:
        return hw, current_stop, False

    mode = settings.trail_mode.lower()
    if mode == "steps":
        trail_stop = _stop_from_steps(entry, gain_pct, settings)
    else:
        trail_stop = hw * (1.0 - settings.trail_distance_pct / 100.0)

    trail_stop = max(current_stop, trail_stop)
    if trail_stop >= target - 1e-9:
        return hw, current_stop, False

    return hw, round(trail_stop, 4), trail_stop > current_stop + 1e-9


def _stop_from_steps(entry: float, gain_pct: float, settings: Settings) -> float:
    steps = parse_trail_steps(settings.trail_steps)
    if not steps:
        return entry
    stop_gain_pct = 0.0
    for threshold, floor_gain in steps:
        if gain_pct >= threshold:
            stop_gain_pct = floor_gain
    return entry * (1.0 + stop_gain_pct / 100.0)
