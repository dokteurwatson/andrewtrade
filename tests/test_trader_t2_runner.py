"""T1 → T2 runner: stage-overgang en backwards-compat state."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from unittest.mock import MagicMock, patch

from stocktrader.config import Settings
from stocktrader.parser import Setup
from stocktrader.state import DayState, Position, StateStore
from stocktrader.trader import Trader


def _settings(**kwargs) -> Settings:
    base = dict(
        paper_capital=1000.0,
        data_source="finazon",
        polygon_api_key="",
        bar_poll_seconds=60,
        alpaca_api_key="",
        alpaca_api_secret="",
        alpaca_data_feed="iex",
        finazon_api_key="k",
        finazon_frequency="10s",
        broker="paper",
        t212_api_key="",
        t212_api_secret="",
        t212_demo=True,
        t212_extended_hours=True,
        fx_eur_usd=1.08,
        fx_gbp_usd=1.27,
        fx_buffer_pct=0.03,
        t212_fx_fee_pct=0.11,
        max_order_usd=500.0,
        max_shares_per_order=0,
        volume_mult=2.0,
        orb_minutes=0,
        trailing_stop_enabled=False,
        trail_mode="trail",
        trail_activation_pct=5.0,
        trail_distance_pct=3.0,
        trail_steps="5:0,10:5,15:10",
        trail_use_close=False,
        stop_sell_limit=False,
        cash_reserve_pct=0.02,
        risk_threshold_usd=200.0,
        risk_per_trade_pct=0.02,
        max_position_pct=0.25,
        max_position_pct_large=0.10,
        large_cap_threshold=10000.0,
        max_positions=3,
        telegram_enabled=False,
        telegram_token="",
        telegram_chat_id="",
        dashboard_port=5001,
        state_dir="./state",
        log_level="INFO",
    )
    base.update(kwargs)
    return Settings(**base)


def _setup() -> Setup:
    return Setup("STAK", hold=3.50, break_=3.90, t1=4.50, t2=5.00)


def _trader_with_position(
    *,
    stop: float = 3.50,
    target: float = 4.50,
    t2: float = 5.00,
    entry: float = 3.90,
) -> Trader:
    mock_broker = MagicMock()
    mock_stream = MagicMock()
    with patch("stocktrader.trader.build_bar_stream", return_value=mock_stream), patch(
        "stocktrader.trader._build_broker_client", return_value=mock_broker
    ):
        trader = Trader(_settings())
    trader._running = True
    state = DayState.empty(date(2026, 6, 4), start_capital=100.0)
    state.setups = [asdict(_setup())]
    state.active = True
    pos = Position(
        ticker="STAK",
        shares=2,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        entry_time="10:00",
        order_id="x",
        t2_price=t2,
    )
    state.positions["STAK"] = asdict(pos)
    trader._state = state
    trader.store = MagicMock()
    return trader


@patch("stocktrader.trader.build_bar_stream")
@patch("stocktrader.trader._build_broker_client")
def test_t1_hit_promotes_to_t2_runner(mock_broker, mock_stream) -> None:
    mock_broker.return_value = MagicMock()
    mock_stream.return_value = MagicMock()
    trader = _trader_with_position()
    trader.notifier = MagicMock()

    trader._on_bar("STAK", 3.9, 4.55, 3.8, 4.5, 1000, is_new_bar=True)

    pos = trader._state.positions["STAK"]
    assert pos["stop_price"] == 4.50
    assert pos["target_price"] == 5.00
    assert pos["runner_active"] is True
    trader.store.save.assert_called_once()
    assert trader._order_queue.qsize() == 0


@patch("stocktrader.trader.build_bar_stream")
@patch("stocktrader.trader._build_broker_client")
def test_t2_hit_exits_at_t2(mock_broker, mock_stream) -> None:
    mock_broker.return_value = MagicMock()
    mock_stream.return_value = MagicMock()
    trader = _trader_with_position(stop=4.50, target=5.00)

    trader._on_bar("STAK", 5.0, 5.10, 4.9, 5.05, 1000, is_new_bar=True)

    action = trader._order_queue.get_nowait()
    assert action[0] == "EXIT"
    assert action[2] == 5.00
    assert action[3] == "T2"


@patch("stocktrader.trader.build_bar_stream")
@patch("stocktrader.trader._build_broker_client")
def test_runner_floor_exit_at_t1(mock_broker, mock_stream) -> None:
    mock_broker.return_value = MagicMock()
    mock_stream.return_value = MagicMock()
    trader = _trader_with_position(stop=4.50, target=5.00)
    trader._state.positions["STAK"]["runner_active"] = True

    trader._on_bar("STAK", 4.6, 4.7, 4.49, 4.5, 1000, is_new_bar=True)

    action = trader._order_queue.get_nowait()
    assert action[0] == "EXIT"
    assert action[2] == 4.50
    assert action[3] == "T1"


@patch("stocktrader.trader.build_bar_stream")
@patch("stocktrader.trader._build_broker_client")
def test_no_t2_closes_at_t1(mock_broker, mock_stream) -> None:
    mock_broker.return_value = MagicMock()
    mock_stream.return_value = MagicMock()
    trader = _trader_with_position(t2=4.50)

    trader._on_bar("STAK", 4.4, 4.55, 4.3, 4.5, 1000, is_new_bar=True)

    action = trader._order_queue.get_nowait()
    assert action[3] == "T1"


def test_position_backwards_compat_missing_t2_price(tmp_path) -> None:
    store = StateStore(str(tmp_path))
    state = DayState.empty(date(2026, 6, 4), start_capital=50.0)
    state.positions["X"] = {
        "ticker": "X",
        "shares": 1,
        "entry_price": 10.0,
        "stop_price": 9.0,
        "target_price": 11.0,
        "entry_time": "09:30",
        "order_id": "old",
    }
    store.save(state)
    loaded = store.load(date(2026, 6, 4))
    pos = loaded.get_positions()["X"]
    assert pos.t2_price == 0.0
