from __future__ import annotations

from stocktrader.parser import parse_watchlist, parse_watchlist_detailed


def test_parse_standard_table() -> None:
    text = """
    Stock  Hold    Break   Target 1  Target 2
    HUBC   $0.35   $0.40   $0.50     $0.60
    MASK   $3.80   $4.20   $6.75     $8.40
    """
    setups = parse_watchlist(text)
    assert [s.ticker for s in setups] == ["HUBC", "MASK"]
    assert setups[0].hold == 0.35
    assert setups[0].break_ == 0.40


def test_parse_telegram_bullets_and_markdown() -> None:
    text = """
    Watchlist vandaag
    1. **MEHA** $0.165 $0.18 $0.20 $0.24
    • TORO 7.00 7.70 8.50 10.00
    - POET $12.80 $13.32 $15.00 $18.00
    """
    tickers = [s.ticker for s in parse_watchlist(text)]
    assert tickers == ["MEHA", "TORO", "POET"]


def test_parse_tabs_and_pipes() -> None:
    text = "ELPW\t2.40\t2.56\t3.00\t3.70\nIQST | 2.45 | 2.72 | 3.50 | 4.20"
    tickers = [s.ticker for s in parse_watchlist(text)]
    assert tickers == ["ELPW", "IQST"]


def test_parse_skips_header_and_invalid_rows() -> None:
    text = """
    STOCK HOLD BREAK TARGET TARGET2
    BAD  1.00  0.50  2.00  3.00
    GOOD 1.00  1.50  2.00  3.00
    """
    setups = parse_watchlist(text)
    assert len(setups) == 1
    assert setups[0].ticker == "GOOD"


def test_parse_reports_skipped_rows() -> None:
    text = """
    STOCK HOLD BREAK TARGET TARGET2
    BAD  1.00  0.50  2.00  3.00
    GOOD 1.00  1.50  2.00  3.00
    """
    result = parse_watchlist_detailed(text)
    assert len(result.setups) == 1
    assert result.setups[0].ticker == "GOOD"
    assert result.skipped >= 1


def test_parse_equal_targets() -> None:
    text = "ABC 1.00 1.50 2.00 2.00"
    setups = parse_watchlist(text)
    assert len(setups) == 1
    assert setups[0].t2 == 2.0
