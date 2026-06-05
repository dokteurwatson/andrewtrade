from stocktrader.parser import Setup
from stocktrader.trader import profit_target_for_entry


def _setup() -> Setup:
    return Setup("TEST", hold=10.0, break_=12.0, t1=13.0, t2=15.0)


def test_profit_target_below_t1_uses_t1() -> None:
    assert profit_target_for_entry(_setup(), 12.50) == 13.0


def test_profit_target_at_or_above_t1_returns_none() -> None:
    assert profit_target_for_entry(_setup(), 13.0) is None
    assert profit_target_for_entry(_setup(), 14.08) is None
    assert profit_target_for_entry(_setup(), 15.0) is None
