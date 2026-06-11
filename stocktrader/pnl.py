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
) -> tuple[float, float]:
    """
    Berekent netto PnL en FX-fee in accountvaluta.

    Tickers zijn USD; op een EUR T212-account moet het resultaat in EUR zijn.
    """
    usd_gross = (exit_price - entry_price) * shares
    fee = 0.0
    if broker == "t212" and fee_pct > 0:
        fee = (entry_price + exit_price) * shares * (fee_pct / 100.0)
    usd_net = usd_gross - fee

    ccy = account_currency.upper()
    if broker == "t212" and ccy != "USD":
        return (
            round(
                convert_usd_to_account(
                    usd_net, ccy,
                    fallback_eur_usd=fx_eur_usd,
                    fallback_gbp_usd=fx_gbp_usd,
                ),
                2,
            ),
            round(
                convert_usd_to_account(
                    fee, ccy,
                    fallback_eur_usd=fx_eur_usd,
                    fallback_gbp_usd=fx_gbp_usd,
                ),
                2,
            ),
        )
    return round(usd_net, 2), round(fee, 2)
