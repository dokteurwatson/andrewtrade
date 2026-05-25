from __future__ import annotations

import ast
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import load_settings
from .exchange import ExchangeClient
from .indicators import rsi, sma


def _read_json(path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return fallback


def _read_trade_lines(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            try:
                rows.append(ast.literal_eval(line))
            except (ValueError, SyntaxError):
                continue
    return rows


def _estimate_potential(exchange: ExchangeClient, symbols: List[str], timeframe: str, sma_period: int, rsi_period: int, rsi_entry_threshold: float) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for symbol in symbols:
        candles = exchange.fetch_candles(symbol, timeframe, max(300, sma_period + rsi_period + 5))
        if len(candles) < max(sma_period, rsi_period + 1):
            continue

        closes = [c.close for c in candles]
        latest_close = closes[-1]
        sma_value = sma(closes, sma_period)
        rsi_value = rsi(closes, rsi_period)
        if sma_value is None or rsi_value is None:
            continue

        trend_ok = latest_close > sma_value
        score = 0.0
        if trend_ok:
            score += 45
        distance = max(rsi_value - rsi_entry_threshold, 0.0)
        score += max(0.0, 55 - distance * 2.5)
        score = max(0.0, min(score, 100.0))

        if trend_ok and rsi_value < rsi_entry_threshold:
            state = "entry_ready"
        elif trend_ok:
            state = "setup_building"
        else:
            state = "trend_not_ready"

        candidates.append(
            {
                "symbol": symbol,
                "state": state,
                "score": round(score, 2),
                "rsi": round(rsi_value, 2),
                "rsi_entry_threshold": rsi_entry_threshold,
                "sma": round(sma_value, 6),
                "close": round(latest_close, 6),
                "trend_ok": trend_ok,
            }
        )

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_state = candidates[0]["state"] if candidates else "unknown"
    avg_score = round(sum(item["score"] for item in candidates) / len(candidates), 2) if candidates else 0.0
    return {
        "portfolio_state": top_state,
        "portfolio_score": avg_score,
        "candidates": candidates,
    }


def _strategy_projection(candles: List[Any], sma_period: int, rsi_period: int, rsi_entry_threshold: float, rsi_exit_threshold: float) -> Dict[str, Any]:
    closes = [c.close for c in candles]
    candle_rows: List[Dict[str, Any]] = []
    sma_rows: List[Dict[str, Any]] = []
    markers: List[Dict[str, Any]] = []
    in_position = False

    for idx, candle in enumerate(candles):
        ts = int(candle.timestamp / 1000)
        candle_rows.append(
            {
                "time": ts,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
            }
        )

        window = closes[: idx + 1]
        sma_value = sma(window, sma_period)
        rsi_value = rsi(window, rsi_period)
        if sma_value is not None:
            sma_rows.append({"time": ts, "value": sma_value})

        if sma_value is None or rsi_value is None:
            continue

        trend_ok = candle.close > sma_value
        should_enter = (not in_position) and trend_ok and rsi_value < rsi_entry_threshold
        should_exit = in_position and rsi_value > rsi_exit_threshold

        if should_enter:
            in_position = True
            markers.append(
                {
                    "time": ts,
                    "position": "belowBar",
                    "color": "#2b8c4a",
                    "shape": "arrowUp",
                    "text": f"ENTRY RSI {rsi_value:.1f}",
                }
            )
        elif should_exit:
            in_position = False
            markers.append(
                {
                    "time": ts,
                    "position": "aboveBar",
                    "color": "#b13d32",
                    "shape": "arrowDown",
                    "text": f"EXIT RSI {rsi_value:.1f}",
                }
            )

    return {
        "candles": candle_rows,
        "sma": sma_rows,
        "markers": markers,
    }


load_dotenv()
settings = load_settings()
state_dir = Path(settings.state_dir)
state_path = state_dir / "paper_state.json"
trades_path = state_dir / "trades.jsonl"

app = FastAPI(title="AndrewTrade Dashboard", version="1.0.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
exchange = ExchangeClient(settings.exchange_id)

# ---------------------------------------------------------------------------
# In-memory TTL cache — avoids hammering Kraken on every page refresh
# ---------------------------------------------------------------------------
_CACHE_TTL = 120  # seconds; 4h candles don't change faster than this

_potential_cache: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)
_chart_cache: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}


@app.get("/")
def root() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/dashboard")
def dashboard_data() -> Dict[str, Any]:
    global _potential_cache

    state = _read_json(
        state_path,
        {
            "cash_usd": settings.start_capital_usd,
            "positions": {},
            "cooldown_remaining": 0,
            "day_key": "",
            "day_start_equity": settings.start_capital_usd,
        },
    )

    trades = _read_trade_lines(trades_path)
    entries = [row for row in trades if row.get("type") == "ENTRY"]
    exits = [row for row in trades if row.get("type") == "EXIT"]

    completed_trades = exits[-50:]
    ongoing_positions = []
    for symbol, value in state.get("positions", {}).items():
        ongoing_positions.append(
            {
                "symbol": symbol,
                "quantity": value.get("quantity", 0),
                "entry_price": value.get("entry_price", 0),
                "entry_timestamp": value.get("entry_timestamp", 0),
                "stop_price": value.get("stop_price", 0),
            }
        )

    # Use cached potential data if still fresh
    cache_ts, cached_potential = _potential_cache
    if cached_potential is not None and (time.monotonic() - cache_ts) < _CACHE_TTL:
        potential = cached_potential
    else:
        try:
            potential = _estimate_potential(
                exchange=exchange,
                symbols=settings.symbols,
                timeframe=settings.timeframe,
                sma_period=settings.sma_period,
                rsi_period=settings.rsi_period,
                rsi_entry_threshold=settings.rsi_entry_threshold,
            )
            _potential_cache = (time.monotonic(), potential)
        except Exception as exc:  # pragma: no cover
            logging.exception("Failed to estimate potential: %s", exc)
            potential = {
                "portfolio_state": "data_unavailable",
                "portfolio_score": 0.0,
                "candidates": [],
                "error": str(exc),
            }

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "exchange": settings.exchange_id,
            "timeframe": settings.timeframe,
            "coins": settings.coin_list,
        },
        "wallet": {
            "cash_usd": round(float(state.get("cash_usd", settings.start_capital_usd)), 6),
            "day_start_equity": round(float(state.get("day_start_equity", settings.start_capital_usd)), 6),
            "cooldown_remaining": int(state.get("cooldown_remaining", 0)),
        },
        "stats": {
            "entries": len(entries),
            "exits": len(exits),
            "open_positions": len(ongoing_positions),
        },
        "ongoing_positions": ongoing_positions,
        "completed_trades": list(reversed(completed_trades)),
        "trade_potential": potential,
    }


@app.get("/api/config")
def config_data() -> Dict[str, Any]:
    return {
        "sma_period": settings.sma_period,
        "rsi_period": settings.rsi_period,
        "rsi_entry_threshold": settings.rsi_entry_threshold,
        "rsi_exit_threshold": settings.rsi_exit_threshold,
        "timeframe": settings.timeframe,
        "candle_limit": settings.candle_limit,
        "start_capital_usd": settings.start_capital_usd,
        "min_order_usd": settings.min_order_usd,
        "slippage_rate": settings.slippage_rate,
        "taker_fee_rate": settings.taker_fee_rate,
        "risk_threshold_balance": settings.risk_threshold_balance,
        "position_sizing_below_threshold": settings.position_sizing_below_threshold,
        "risk_per_trade_above_threshold": settings.risk_per_trade_above_threshold,
        "stop_loss_pct_above_threshold": settings.stop_loss_pct_above_threshold,
        "max_daily_loss_above_threshold": settings.max_daily_loss_above_threshold,
        "max_open_positions_above_threshold": settings.max_open_positions_above_threshold,
        "max_consecutive_losses_above_threshold": settings.max_consecutive_losses_above_threshold,
        "cooldown_candles_after_limit": settings.cooldown_candles_after_limit,
        "poll_seconds": settings.poll_seconds,
        "bugatti_target_usd": settings.bugatti_target_usd,
        "mode": settings.mode,
        "exchange_id": settings.exchange_id,
        "coin_list": settings.coin_list,
    }



@app.get("/api/chart")
def chart_data(symbol: str | None = None, limit: int = 300) -> Dict[str, Any]:
    selected_symbol = symbol if symbol in settings.symbols else settings.symbols[0]
    safe_limit = max(100, min(limit, 800))
    cache_key = f"{selected_symbol}:{safe_limit}"

    cache_ts, cached_projection = _chart_cache.get(cache_key, (0.0, None))
    if cached_projection is not None and (time.monotonic() - cache_ts) < _CACHE_TTL:
        projection = cached_projection
    else:
        try:
            candles = exchange.fetch_candles(selected_symbol, settings.timeframe, safe_limit)
            projection = _strategy_projection(
                candles=candles,
                sma_period=settings.sma_period,
                rsi_period=settings.rsi_period,
                rsi_entry_threshold=settings.rsi_entry_threshold,
                rsi_exit_threshold=settings.rsi_exit_threshold,
            )
            _chart_cache[cache_key] = (time.monotonic(), projection)
        except Exception as exc:  # pragma: no cover
            logging.exception("Failed to build chart projection: %s", exc)
            projection = {"candles": [], "sma": [], "markers": [], "error": str(exc)}
    return {
        "symbol": selected_symbol,
        "timeframe": settings.timeframe,
        "projection": projection,
    }
