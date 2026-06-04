"""
Sluit alle open US-aandelenposities — paper/liquidatie.

- Chunks van 500 (default)
- LIMIT DAY dicht bij markt (IB weigert >~10% onder ref, Warning 202)
- Bij reject: prijs omhoog (dichter bij markt), niet verder omlaag
- usePriceMgmtAlgo=False

  python -m stocktrader.close_all_ibkr --yes --chunk 500 --timeout 120
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
import re
import sys

from ib_insync import IB, LimitOrder, util

from stocktrader.config import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("close_all_ibkr")

TERMINAL_BAD = frozenset({"CANCELLED", "INACTIVE", "APICANCELLED"})
WORKING = frozenset({"SUBMITTED", "PRESUBMITTED", "PENDINGSUBMIT", "PENDINGCANCEL", ""})
# SELL: start 2% onder ref; bij IB 202 stap naar bid/markt (max ~0% korting)
SELL_DISCOUNTS = (0.02, 0.01, 0.005, 0.0)


def _apply_market_data_type(ib: IB) -> None:
    raw = os.getenv("IBKR_MARKET_DATA_TYPE", "delayed")
    mdt = Settings._parse_market_data_type(raw)
    labels = {1: "live", 2: "frozen", 3: "delayed", 4: "delayed_frozen"}
    try:
        ib.reqMarketDataType(mdt)
        log.info("Market data type=%s (%s)", mdt, labels.get(mdt, raw))
    except Exception as e:
        log.warning("reqMarketDataType mislukt: %s", e)


async def _refresh_positions(ib: IB, wait_sec: float = 1.5) -> list:
    ib.reqPositions()
    await asyncio.sleep(wait_sec)
    return [
        p for p in ib.positions()
        if p.position != 0 and getattr(p.contract, "secType", "") == "STK"
    ]


def _portfolio_price(ib: IB, contract) -> float | None:
    for item in ib.portfolio():
        if item.contract.symbol == contract.symbol and item.marketPrice and item.marketPrice > 0:
            return float(item.marketPrice)
    return None


def _round_price(price: float) -> float:
    if price >= 1:
        return round(price, 2)
    if price >= 0.1:
        return round(price, 4)
    return max(0.0001, round(price, 6))


def _resolve_chunk_size(cli_chunk: int) -> int:
    """MAX_ORDER_SHARES uit env (default 500); --chunk mag niet hoger."""
    lim = Settings.from_env().effective_max_order_shares()
    if cli_chunk <= 0:
        return lim
    if cli_chunk > lim:
        log.warning("--chunk %d > MAX_ORDER_SHARES %d, gebruik %d", cli_chunk, lim, lim)
        return lim
    return cli_chunk


def _chunk_qty(remaining: int, chunk_size: int) -> int:
    return min(remaining, chunk_size) if chunk_size > 0 else remaining


def _trade_log_text(trade) -> str:
    return " ".join(str(e) for e in (trade.log or []))


def _parse_ib_price_cap(text: str) -> tuple[float | None, float | None]:
    """IB Warning 202: min SELL limit + optionele marktprijs uit melding."""
    floor = None
    market = None
    m = re.search(r"more aggressive than ([\d.]+)", text, re.I)
    if m:
        floor = float(m.group(1))
    m = re.search(r"market price of ([\d.]+)", text, re.I)
    if m:
        market = float(m.group(1))
    return floor, market


def _limit_price(
    side: str,
    ref: float,
    attempt: int,
    *,
    ib_floor: float | None,
) -> float:
    """SELL: niet onder IB-floor; bij reject attempt omhoog = dichter bij markt."""
    if side == "SELL":
        disc = SELL_DISCOUNTS[min(attempt, len(SELL_DISCOUNTS) - 1)]
        price = ref * (1.0 - disc)
        if ib_floor and ib_floor > 0:
            price = max(price, ib_floor)
        return _round_price(price)
    disc = SELL_DISCOUNTS[min(attempt, len(SELL_DISCOUNTS) - 1)]
    price = ref * (1.0 + disc)
    return _round_price(price)


async def _snapshot_price(ib: IB, contract, side: str) -> float | None:
    ticker = ib.reqMktData(contract, "", True, False)
    try:
        for _ in range(20):
            await asyncio.sleep(0.25)
            bid, ask = float(ticker.bid or 0), float(ticker.ask or 0)
            last = float(ticker.last or ticker.close or 0)
            if side == "SELL":
                return bid if bid > 0 else (last if last > 0 else None)
            return ask if ask > 0 else (last if last > 0 else None)
    finally:
        ib.cancelMktData(contract)


async def _reference_price(ib: IB, contract, side: str) -> float:
    snap = await _snapshot_price(ib, contract, side)
    if snap and snap > 0:
        return snap
    px = _portfolio_price(ib, contract)
    if px and px > 0:
        return px
    raise RuntimeError(f"geen marktprijs voor {contract.symbol}")


async def _wait_done(trade, label: str, timeout_sec: float) -> float:
    deadline = asyncio.get_event_loop().time() + timeout_sec
    last_st = ""
    while asyncio.get_event_loop().time() < deadline:
        os_ = trade.orderStatus
        st = (os_.status or "").upper()
        last_st = st
        filled = float(os_.filled or 0)
        remaining = float(os_.remaining if os_.remaining is not None else 0)
        if st == "FILLED" or (filled > 0 and remaining == 0):
            return filled
        if st in TERMINAL_BAD:
            if filled > 0:
                return filled
            raise RuntimeError(f"{label} {st}: {_trade_log_text(trade)}")
        await asyncio.sleep(0.25)
    filled = float(trade.orderStatus.filled or 0)
    if filled > 0:
        return filled
    st = (trade.orderStatus.status or "").upper()
    if st in WORKING:
        return 0.0
    raise RuntimeError(f"{label} timeout ({last_st})")


async def _cancel_trade(ib: IB, trade) -> None:
    st = (trade.orderStatus.status or "").upper()
    if st in WORKING or st == "SUBMITTED":
        ib.cancelOrder(trade.order)
        for _ in range(16):
            await asyncio.sleep(0.25)
            if (trade.orderStatus.status or "").upper() in TERMINAL_BAD | {"FILLED"}:
                break


async def _sell_chunk(
    ib: IB,
    contract,
    side: str,
    qty: int,
    label: str,
    *,
    timeout_sec: float,
    attempt: int,
    ib_floor: float | None,
) -> float:
    ref = await _reference_price(ib, contract, side)
    price = _limit_price(side, ref, attempt, ib_floor=ib_floor)
    order = LimitOrder(side, qty, price, tif="DAY")
    order.usePriceMgmtAlgo = False
    log.info(
        "%s LIMIT DAY %s x%d @ %s (ref %.4f, floor %s, poging %d)",
        label, side, qty, price, ref, ib_floor, attempt,
    )
    trade = ib.placeOrder(contract, order)
    try:
        filled = await _wait_done(trade, label, timeout_sec)
    except RuntimeError:
        raise
    if filled <= 0:
        await _cancel_trade(ib, trade)
        raise RuntimeError(f"{label} 0 fill @ {price}: {_trade_log_text(trade)}")
    return filled


async def _close_symbol(
    ib: IB,
    sym: str,
    *,
    chunk_size: int,
    order_timeout_sec: float,
) -> None:
    contract = None
    side = "SELL"
    chunk_no = 0
    attempt = 0
    ib_floor: float | None = None

    while True:
        open_pos = await _refresh_positions(ib)
        current = next(
            (p for p in open_pos if p.contract.symbol == sym and p.position != 0),
            None,
        )
        if not current:
            log.info("%s — weg.", sym)
            return

        if contract is None:
            contract = current.contract
            side = "SELL" if current.position > 0 else "BUY"

        remaining = abs(int(current.position))
        qty = _chunk_qty(remaining, chunk_size)
        chunk_no += 1
        label = f"{side} {sym} #{chunk_no} x{qty} (rest {remaining})"

        try:
            filled = await _sell_chunk(
                ib, contract, side, qty, label,
                timeout_sec=order_timeout_sec,
                attempt=attempt,
                ib_floor=ib_floor,
            )
            log.info("%s → filled %s", label, filled)
            attempt = 0
            ib_floor = None
        except RuntimeError as e:
            err = str(e)
            cap_floor, cap_mkt = _parse_ib_price_cap(err)
            if cap_floor:
                ib_floor = cap_floor
                log.warning(
                    "%s: IB min limit %.4f (markt %.4f) — prijs omhoog",
                    sym,
                    cap_floor,
                    cap_mkt or 0,
                )
                attempt = 0
            else:
                log.warning("%s: %s — dichter bij markt", sym, e)
                attempt = min(attempt + 1, len(SELL_DISCOUNTS) - 1)
            await asyncio.sleep(2)

        await asyncio.sleep(0.2)


async def run(
    *,
    dry_run: bool,
    order_timeout_sec: float,
    chunk_size: int,
    symbols_filter: list[str] | None,
) -> int:
    host = os.getenv("IBKR_HOST", "ib-gateway")
    port = int(os.getenv("IBKR_PORT", "4002"))
    client_id = int(os.getenv("IBKR_CLOSE_CLIENT_ID", "2"))
    chunk_size = _resolve_chunk_size(chunk_size)

    util.logToFile(f"close_all_ibkr_client_{client_id}.log")
    util.logToConsole(logging.WARNING)
    ib = IB()
    log.info("Verbinden %s:%d clientId=%d chunk=%d ...", host, port, client_id, chunk_size)
    try:
        await ib.connectAsync(host, port, clientId=client_id)
    except Exception as e:
        log.error("Kon niet verbinden: %s", e)
        return 1

    _apply_market_data_type(ib)
    open_pos = await _refresh_positions(ib, wait_sec=2.5)

    if symbols_filter:
        want = {s.upper() for s in symbols_filter}
        open_pos = [p for p in open_pos if p.contract.symbol.upper() in want]

    if not open_pos:
        log.info("Geen open stock-posities.")
        ib.disconnect()
        return 0

    log.info("Modus: LIMIT DAY bij markt, chunks=%d, timeout=%.0fs", chunk_size, order_timeout_sec)
    for p in open_pos:
        rem = abs(int(p.position))
        n = math.ceil(rem / chunk_size) if chunk_size else 1
        log.info("  %s qty=%s → ~%d orders x%d", p.contract.symbol, p.position, n, chunk_size)

    if dry_run:
        log.info("Dry-run klaar — geen orders geplaatst.")
        ib.disconnect()
        return 0

    for p in open_pos:
        await _close_symbol(
            ib, p.contract.symbol,
            chunk_size=chunk_size,
            order_timeout_sec=order_timeout_sec,
        )

    left = await _refresh_positions(ib)
    ib.disconnect()
    if left:
        log.error("Nog open: %s", [(p.contract.symbol, p.position) for p in left])
        return 1
    log.info("Klaar — alles verkocht.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verkoop alle IBKR posities (agressief, chunks)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0, help="Sec wachten per chunk")
    parser.add_argument(
        "--chunk",
        type=int,
        default=0,
        help="Stuks per order (0 = MAX_ORDER_SHARES uit env, default 500)",
    )
    parser.add_argument("--symbol", action="append", dest="symbols")
    args = parser.parse_args(argv)

    if not args.dry_run and not args.yes and sys.stdin.isatty():
        print(f"Verkoopt alles in chunks van {_resolve_chunk_size(args.chunk)} (verlies OK).")
        if input("Doorgaan? [y/N] ").strip().lower() != "y":
            return 0

    util.patchAsyncio()
    return asyncio.run(
        run(
            dry_run=args.dry_run,
            order_timeout_sec=args.timeout,
            chunk_size=_resolve_chunk_size(args.chunk),
            symbols_filter=args.symbols,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
