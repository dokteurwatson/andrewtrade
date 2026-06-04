from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from ccxt.base.errors import NetworkError

from papertrader.exchange import ExchangeClient, OrderFill
from tests.conftest import make_settings


def test_fetch_candles_retries_on_network_error() -> None:
    client = ExchangeClient("kraken")
    mock_client = MagicMock()
    mock_client.fetch_ohlcv.side_effect = [
        NetworkError("fail"),
        [[1, 1.0, 2.0, 0.5, 1.5, 10.0]],
    ]
    mock_client.load_markets.return_value = None
    client._client = mock_client
    client._markets_loaded = True

    with patch("papertrader.exchange.time.sleep"):
        candles = client.fetch_candles("BTC/USD", "4h", 1)

    assert len(candles) == 1
    assert candles[0].close == 1.5
    assert mock_client.fetch_ohlcv.call_count == 2


def test_create_market_buy_parses_fill() -> None:
    client = ExchangeClient("kraken", api_key="k", api_secret="s")
    mock_client = MagicMock()
    mock_client.create_order.return_value = {
        "id": "abc",
        "filled": 0.5,
        "average": 100.0,
        "fees": [{"cost": 0.13}],
    }
    mock_client.load_markets.return_value = None
    client._client = mock_client
    client._markets_loaded = True

    fill = client.create_market_buy("BTC/USD", 50.0)

    assert fill == OrderFill(symbol="BTC/USD", quantity=0.5, price=100.0, fee=0.13, order_id="abc")
    mock_client.create_order.assert_called_once()


def test_create_market_sell_parses_fill() -> None:
    client = ExchangeClient("kraken", api_key="k", api_secret="s")
    mock_client = MagicMock()
    mock_client.create_order.return_value = {
        "id": "sell-1",
        "filled": 1.0,
        "average": 99.0,
        "fee": {"cost": 0.25},
    }
    mock_client.load_markets.return_value = None
    client._client = mock_client
    client._markets_loaded = True

    fill = client.create_market_sell("BTC/USD", 1.0)

    assert fill.quantity == 1.0
    assert fill.price == 99.0
    assert fill.fee == 0.25


def test_fetch_usd_balance_prefers_usd() -> None:
    client = ExchangeClient("kraken", api_key="k", api_secret="s")
    mock_client = MagicMock()
    mock_client.fetch_balance.return_value = {"USD": {"free": 123.45}}
    mock_client.load_markets.return_value = None
    client._client = mock_client
    client._markets_loaded = True

    assert client.fetch_usd_balance() == 123.45


def test_validate_settings_rejects_live_without_gate(tmp_path) -> None:
    from papertrader.config import validate_settings

    settings = make_settings(tmp_path, mode="live", live_trading_enabled=False, kraken_api_key="k", kraken_api_secret="s")
    with pytest.raises(RuntimeError, match="LIVE_TRADING_ENABLED"):
        validate_settings(settings)
