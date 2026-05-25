from __future__ import annotations

from papertrader.config import _parse_coin_list, load_settings


def test_parse_coin_list_defaults() -> None:
    assert _parse_coin_list(None) == ["BTC", "ETH", "XRP"]


def test_parse_coin_list_supports_json_array() -> None:
    assert _parse_coin_list('["btc", "eth", "xrp", "doge"]') == ["BTC", "ETH", "XRP", "DOGE"]


def test_parse_coin_list_supports_csv() -> None:
    assert _parse_coin_list("btc, eth ,xrp") == ["BTC", "ETH", "XRP"]


def test_load_settings_uses_env(monkeypatch) -> None:
    monkeypatch.setenv("COIN_LIST", '["BTC","DOGE"]')
    monkeypatch.setenv("TIMEFRAME", "4h")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    settings = load_settings()

    assert settings.coin_list == ["BTC", "DOGE"]
    assert settings.symbols == ["BTC/USD", "DOGE/USD"]
    assert settings.log_level == "DEBUG"
