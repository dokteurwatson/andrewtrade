"""PnL-berekening — USD tickers, accountvaluta (EUR/GBP/USD) op T212."""
from __future__ import annotations

from .fx_rates import convert_usd_to_account


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
    fx_fee_fixed: float = 0.0,
    entry_fx_fee: float = 0.0,
) -> tuple[float, float]:
    """
    Berekent netto PnL en totale FX-fee in accountvaluta.

    T212 EUR: bruto (exit-entry)*shares omgerekend naar EUR, minus FX-fee op
    koop (entry_fx_fee) en verkoop (fx_fee_fixed). Zo sluit Dag PnL aan op
    het werkelijke saldo-effect inclusief conversiekosten.
    """
    usd_gross = (exit_price - entry_price) * shares
    ccy = account_currency.upper()
    is_t212_fx = broker == "t212" and ccy != "USD"

    if is_t212_fx:
        gross = convert_usd_to_account(
            usd_gross, ccy,
            fallback_eur_usd=fx_eur_usd,
            fallback_gbp_usd=fx_gbp_usd,
        )
        entry_fx = entry_fx_fee if entry_fx_fee > 0 else fx_fee_fixed
        exit_fx = fx_fee_fixed
        if fx_fee_fixed <= 0 and fee_pct > 0:
            pct_usd = (entry_price + exit_price) * shares * (fee_pct / 100.0)
            fee = convert_usd_to_account(
                pct_usd, ccy,
                fallback_eur_usd=fx_eur_usd,
                fallback_gbp_usd=fx_gbp_usd,
            )
        else:
            fee = entry_fx + exit_fx
        return round(gross - fee, 2), round(fee, 2)

    fee = 0.0
    if broker == "t212" and fee_pct > 0:
        fee = (entry_price + exit_price) * shares * (fee_pct / 100.0)
    return round(usd_gross - fee, 2), round(fee, 2)
