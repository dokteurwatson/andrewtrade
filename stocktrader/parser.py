"""
Parser voor Krush's watchlist formaat.

Ondersteunt zowel platte tekst (copy-paste uit Discord/Telegram) als
gestructureerde tabel met kolommen: Stock Hold Break Target1 Target2.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List


@dataclass
class Setup:
    ticker: str
    hold:   float
    break_: float
    t1:     float
    t2:     float
    enabled: bool = True

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


@dataclass
class ParseResult:
    setups: List[Setup]
    skipped: int   # aantal rijen die genegeerd zijn (ongeldig/duplicaat/header)
    matched: int   # aantal regex-matches gevonden


_PRICE = r"\$?\s*([\d]{1,3}(?:[,\s][\d]{3})*(?:\.[\d]+)?|[\d]+\.?[\d]*)"
# Ticker: 1-5 letters, optioneel .X (BRK.B); prefix bullets/stars weg in _normalize
_TICKER = r"([A-Z]{1,5}(?:\.[A-Z])?)"
_ROW = re.compile(
    rf"{_TICKER}\s+{_PRICE}\s+{_PRICE}\s+{_PRICE}\s+{_PRICE}",
    re.IGNORECASE,
)

_SKIP_WORDS = {
    "STOCK", "HOLD", "BREAK", "TARGET", "TARGET1", "TARGET2",
    "WATCHLIST", "SETUP", "SETUPS", "TICKER", "SYMBOL",
}


def _normalize_watchlist_text(text: str) -> str:
    """Maak Telegram/Discord copy-paste parser-vriendelijk."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ").replace("|", " ")
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)   # **HUBC** → HUBC
    text = re.sub(r"`([^`]+)`", r"\1", text)
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # bullets: "1.", "•", "-", "▪"
        line = re.sub(r"^[\s\*•▪\-\u2022]+", "", line)
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        lines.append(line)
    return "\n".join(lines)


def _parse_price(raw: str) -> float:
    cleaned = raw.replace(",", "").replace(" ", "")
    return float(cleaned)


def valid_setup(hold: float, break_: float, t1: float, t2: float) -> bool:
    if not (hold > 0 and break_ > hold and t1 > break_):
        return False
    # T2 mag gelijk of hoger zijn dan T1; soms staat alleen één target dubbel
    return t2 > 0 and t2 >= t1 * 0.99


def parse_watchlist_detailed(text: str) -> ParseResult:
    """
    Parst Krush's watchlist tekst naar setups + statistieken.

    Returns ParseResult met setups, skipped count en matched count.
    """
    normalized = _normalize_watchlist_text(text)
    setups: List[Setup] = []
    seen: set[str] = set()
    skipped = 0
    matched = 0

    for match in _ROW.finditer(normalized):
        matched += 1
        ticker = match.group(1).upper()
        if ticker in _SKIP_WORDS:
            skipped += 1
            continue
        if ticker in seen:
            skipped += 1
            continue

        try:
            hold   = _parse_price(match.group(2))
            break_ = _parse_price(match.group(3))
            t1     = _parse_price(match.group(4))
            t2     = _parse_price(match.group(5))
        except ValueError:
            skipped += 1
            continue

        if not valid_setup(hold, break_, t1, t2):
            skipped += 1
            continue

        seen.add(ticker)
        setups.append(Setup(ticker=ticker, hold=hold, break_=break_, t1=t1, t2=t2))

    return ParseResult(setups=setups, skipped=skipped, matched=matched)


def parse_watchlist(text: str) -> List[Setup]:
    """
    Parst Krush's watchlist tekst naar een lijst van Setups.

    Accepteert rijen zoals:
        HUBC   $0.35   $0.40   $0.50   $0.60
        ASTC   48.00   52.00   60.00    70.00
        • MEHA 0.165 0.18 0.20 0.24
    """
    return parse_watchlist_detailed(text).setups


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
