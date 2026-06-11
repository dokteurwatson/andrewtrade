"""PnL-berekening — USD tickers, accountvaluta (EUR/GBP/USD) op T212."""
from __future__ import annotations

from .fx_rates import get_rate_to_usd


def _spot_rate(
    currency: str,
    *,
    fx_eur_usd: float,
    fx_gbp_usd: float,
) -> float:
    """Live EURUSD/GBPUSD (1 accountvaluta = X USD), zonder sizing-buffer."""
    return get_rate_to_usd(
        currency,
        fallback_eur_usd=fx_eur_usd,
        fallback_gbp_usd=fx_gbp_usd,
        buffer_pct=0.0,
    )


def t212_usd_to_account(
    usd: float,
    spot: float,
    *,
    side: str,
    fee_pct: float,
) -> float:
    """
    T212 FX: fee ingebakken in conversiekoers.

    Buy  (EUR→USD): rate = spot × (1 − fee%)
    Sell (USD→EUR): rate = spot × (1 + fee%)
    """
    f = fee_pct / 100.0
    if side == "buy":
        return usd / (spot * (1.0 - f))
    return usd / (spot * (1.0 + f))


def compute_entry_eur_cost(
    *,
    entry_price: float,
    shares: int,
    fee_pct: float,
    fx_eur_usd: float = 1.08,
    fx_gbp_usd: float = 1.27,
    account_currency: str = "EUR",
    spot: float | None = None,
) -> float:
    """EUR-kostprijs bij entry (T212 buy-rate), vast te leggen op de positie."""
    ccy = account_currency.upper()
    rate = spot if spot is not None else _spot_rate(ccy, fx_eur_usd=fx_eur_usd, fx_gbp_usd=fx_gbp_usd)
    return t212_usd_to_account(
        entry_price * shares, rate, side="buy", fee_pct=fee_pct,
    )


def compute_trade_pnl(
    *,
    entry_price: float,
    exit_price: float,
    shares: int,
    broker: str,
    fee_pct: float,
    account_currency: str = "USD",
    fx_eur_usd: float = 1.08,
    fx_gbp_usd: float = 1.27,
    entry_eur_cost: float = 0.0,
) -> tuple[float, float]:
    """
    Berekent netto PnL en totale FX-fee in accountvaluta.

    T212 EUR: sell_eur − entry_eur_cost, waarbij elke leg de T212-rate
    (0,15% in de koers) gebruikt.
    """
    usd_gross = (exit_price - entry_price) * shares
    ccy = account_currency.upper()
    is_t212_fx = broker == "t212" and ccy != "USD"

    if is_t212_fx and fee_pct > 0:
        spot = _spot_rate(ccy, fx_eur_usd=fx_eur_usd, fx_gbp_usd=fx_gbp_usd)
        usd_entry = entry_price * shares
        usd_exit = exit_price * shares
        buy_eur = (
            entry_eur_cost
            if entry_eur_cost > 0
            else t212_usd_to_account(usd_entry, spot, side="buy", fee_pct=fee_pct)
        )
        sell_eur = t212_usd_to_account(usd_exit, spot, side="sell", fee_pct=fee_pct)
        pnl = sell_eur - buy_eur
        fee = (buy_eur - usd_entry / spot) + (usd_exit / spot - sell_eur)
        return round(pnl, 2), round(fee, 2)

    fee = 0.0
    if broker == "t212" and fee_pct > 0:
        fee = (entry_price + exit_price) * shares * (fee_pct / 100.0)
    return round(usd_gross - fee, 2), round(fee, 2)
