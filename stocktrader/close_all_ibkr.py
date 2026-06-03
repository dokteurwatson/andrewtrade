"""
Sluit alle open US-aandelenposities via IB Gateway (market orders, in chunks).

Gebruik in de dashboard-pod (zelfde env als de bot):

  # Bot eerst stoppen op het dashboard, anders clientId-conflict
  python -m stocktrader.close_all_ibkr --yes

  # Alleen tonen wat er zou gebeuren:
  python -m stocktrader.close_all_ibkr --dry-run

Optioneel andere clientId (default 2, bot gebruikt vaak 1):

  IBKR_CLOSE_CLIENT_ID=3 python -m stocktrader.close_all_ibkr --yes
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from ib_insync import IB, MarketOrder, util

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("close_all_ibkr")


def _chunk_shares(total: int, chunk_size: int) -> list[int]:
    if chunk_size <= 0 or total <= chunk_size:
        return [total]
    parts: list[int] = []
    left = total
    while left > 0:
        q = min(chunk_size, left)
        parts.append(q)
        left -= q
    return parts


async def _wait_filled(trade, label: str) -> None:
    for _ in range(50):
        st = (trade.orderStatus.status or "").upper()
        if st == "FILLED":
            return
        if st in ("CANCELLED", "INACTIVE", "APICANCELLED"):
            raise RuntimeError(f"{label} {st}: {trade.log}")
        await asyncio.sleep(0.25)
    st = (trade.orderStatus.status or "").upper()
    if st != "FILLED":
        raise RuntimeError(f"{label} timeout status={st}")


async def run(*, dry_run: bool) -> int:
    host = os.getenv("IBKR_HOST", "ib-gateway")
    port = int(os.getenv("IBKR_PORT", "4002"))
    # Default 2 — niet 1, anders conflict met draaiende dashboard/trader (IBKR_CLIENT_ID=1)
    client_id = int(os.getenv("IBKR_CLOSE_CLIENT_ID", "2"))
    max_chunk = int(os.getenv("MAX_ORDER_SHARES", "500"))

    ib = IB()
    log.info("Verbinden %s:%d clientId=%d ...", host, port, client_id)
    await ib.connectAsync(host, port, clientId=client_id)
    ib.reqPositions()
    await asyncio.sleep(2)

    open_pos = [
        p for p in ib.positions()
        if p.position != 0 and getattr(p.contract, "secType", "") == "STK"
    ]
    if not open_pos:
        log.info("Geen open stock-posities.")
        ib.disconnect()
        return 0

    log.info("%d ticker(s) met open positie:", len(open_pos))
    for p in open_pos:
        log.info("  %s qty=%s avgCost=%s", p.contract.symbol, p.position, p.avgCost)

    if dry_run:
        log.info("Dry-run — geen orders geplaatst.")
        ib.disconnect()
        return 0

    for pos in open_pos:
        sym = pos.contract.symbol
        total = abs(int(pos.position))
        side = "SELL" if pos.position > 0 else "BUY"
        chunks = _chunk_shares(total, max_chunk)
        log.info("%s %s totaal %d in %d order(s)", side, sym, total, len(chunks))
        for i, qty in enumerate(chunks, start=1):
            order = MarketOrder(side, qty)
            trade = ib.placeOrder(pos.contract, order)
            label = f"{side} {sym} {i}/{len(chunks)} x{qty}"
            await _wait_filled(trade, label)
            log.info("%s FILLED orderId=%s", label, trade.order.orderId)
            if i < len(chunks):
                await asyncio.sleep(0.35)

    ib.reqPositions()
    await asyncio.sleep(1)
    left = [p for p in ib.positions() if p.position != 0 and p.contract.secType == "STK"]
    ib.disconnect()
    if left:
        log.error("Nog %d open positie(s): %s", len(left), [p.contract.symbol for p in left])
        return 1
    log.info("Klaar — alle stock-posities gesloten.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sluit alle IBKR stock-posities")
    parser.add_argument("--dry-run", action="store_true", help="Alleen tonen, geen orders")
    parser.add_argument("--yes", action="store_true", help="Geen bevestiging (voor kubectl exec)")
    args = parser.parse_args(argv)

    if not args.dry_run and not args.yes and sys.stdin.isatty():
        print("Dit plaatst MARKET orders om ALLE stock-posities te sluiten.")
        if input("Doorgaan? [y/N] ").strip().lower() != "y":
            print("Afgebroken.")
            return 0

    util.patchAsyncio()
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
