"""
Parser voor Krush's watchlist formaat.

Ondersteunt zowel platte tekst (copy-paste uit Discord) als
gestructureerde tabel met kolommen: Stock Hold Break Target1 Target2.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Setup:
    ticker: str
    hold:   float
    break_: float
    t1:     float
    t2:     float

    def risk_pct(self) -> float:
        """Verlies als % van break prijs bij stop."""
        return (self.break_ - self.hold) / self.break_ * 100

    def rr_t1(self) -> float:
        """Risk/reward ratio naar T1."""
        risk   = self.break_ - self.hold
        reward = self.t1 - self.break_
        return reward / risk if risk > 0 else 0

    def rr_t2(self) -> float:
        """Risk/reward ratio naar T2."""
        risk   = self.break_ - self.hold
        reward = self.t2 - self.break_
        return reward / risk if risk > 0 else 0


# Patroon: ticker + 4 prijzen (met optionele $)
_PRICE = r'\$?([\d]+\.?[\d]*)'
_ROW   = re.compile(
    rf'^([A-Z]{{1,6}})\s+{_PRICE}\s+{_PRICE}\s+{_PRICE}\s+{_PRICE}',
    re.MULTILINE,
)


def parse_watchlist(text: str) -> List[Setup]:
    """
    Parst Krush's watchlist tekst naar een lijst van Setups.

    Accepteert elke tekst die rijen bevat zoals:
        HUBC   $0.35   $0.40   $0.50   $0.60
        ASTC   48.00   52.00   60.00   70.00

    Regels met header-woorden (Stock, Hold, Break, etc.) worden overgeslagen.
    """
    skip = {"STOCK", "HOLD", "BREAK", "TARGET", "TARGET1", "TARGET2"}
    setups: List[Setup] = []
    seen: set[str] = set()

    for match in _ROW.finditer(text):
        ticker = match.group(1).upper()
        if ticker in skip:
            continue
        if ticker in seen:
            continue  # duplicaten overslaan (zelfde ticker meerdere keren in bericht)
        seen.add(ticker)

        try:
            hold   = float(match.group(2))
            break_ = float(match.group(3))
            t1     = float(match.group(4))
            t2     = float(match.group(5))
        except ValueError:
            continue

        # Sanity checks
        if not (0 < hold < break_ < t1 <= t2):
            continue

        setups.append(Setup(ticker=ticker, hold=hold, break_=break_, t1=t1, t2=t2))

    return setups


def format_setups(setups: List[Setup]) -> str:
    """Human-readable overzicht van geparsde setups."""
    if not setups:
        return "Geen geldige setups gevonden."

    lines = [
        f"{'Ticker':<8} {'Hold':>8} {'Break':>8} {'T1':>8} {'T2':>8} {'R:R T1':>8} {'Stop%':>7}",
        "-" * 60,
    ]
    for s in setups:
        lines.append(
            f"{s.ticker:<8} ${s.hold:>7.2f} ${s.break_:>7.2f} ${s.t1:>7.2f} "
            f"${s.t2:>7.2f} {s.rr_t1():>7.1f}x {s.risk_pct():>6.1f}%"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    # Test met gisteren's watchlist
    sample = """
    Stock  Hold    Break   Target 1  Target 2
    HUBC   $0.35   $0.40   $0.50     $0.60
    ASTC   $48.00  $52.00  $60.00    $70.00
    NAMM   $2.35   $2.49   $3.00     $4.40
    MX     $9.30   $9.78   $11.00    $13.00
    MASK   $3.80   $4.20   $6.75     $8.40
    """
    setups = parse_watchlist(sample)
    print(format_setups(setups))
