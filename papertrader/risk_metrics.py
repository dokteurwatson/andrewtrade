from __future__ import annotations

from typing import Any, Dict, Optional


def enrich_ongoing_position(
    *,
    symbol: str,
    quantity: float,
    entry_price: float,
    stop_price: float,
    entry_timestamp: int,
    total_equity: float,
    mark_price: Optional[float] = None,
) -> Dict[str, Any]:
    stop_active = stop_price > 0
    price = mark_price if mark_price is not None else entry_price
    position_value = quantity * price

    if stop_active:
        risk_usd = quantity * max(entry_price - stop_price, 0.0)
        stop_loss_pct = (entry_price - stop_price) / entry_price * 100 if entry_price > 0 else 0.0
    else:
        risk_usd = position_value
        stop_loss_pct = None

    risk_pct = (risk_usd / total_equity * 100) if total_equity > 0 else 0.0
    unrealized = quantity * (price - entry_price)

    return {
        "symbol": symbol,
        "quantity": quantity,
        "entry_price": entry_price,
        "entry_timestamp": entry_timestamp,
        "stop_price": stop_price,
        "stop_active": stop_active,
        "stop_status": "Active" if stop_active else "Inactive",
        "stop_loss_pct": round(stop_loss_pct, 4) if stop_loss_pct is not None else None,
        "position_value_usd": round(position_value, 6),
        "risk_usd": round(risk_usd, 6),
        "risk_pct_of_equity": round(risk_pct, 4),
        "unrealized_pnl_usd": round(unrealized, 6),
        "mark_price": round(price, 6),
    }


def enrich_completed_trade(exit_row: Dict[str, Any]) -> Dict[str, Any]:
    entry_price = exit_row.get("entry_price")
    stop_price = exit_row.get("stop_price")
    exit_price = exit_row.get("exit_price", exit_row.get("price"))

    def _num(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        return float(value)

    return {
        "symbol": exit_row.get("symbol"),
        "entry_price": _num(entry_price),
        "stop_price": _num(stop_price),
        "exit_price": _num(exit_price),
        "pnl": _num(exit_row.get("pnl")),
        "pnl_label": "Profit/Loss in USD (net after fees)",
        "reason": exit_row.get("reason"),
        "quantity": _num(exit_row.get("quantity")),
        "timestamp": exit_row.get("timestamp"),
        "risk_mode": exit_row.get("risk_mode"),
    }
