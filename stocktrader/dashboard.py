"""
Flask dashboard — watchlist uploaden en bot beheren (paper trading).

Start: python -m stocktrader.dashboard
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from .config import Settings
from .market_snapshot import (
    apply_follow_status,
    enrich_quotes_with_reference,
    placeholder_snapshots,
    prefetch_reference_prices,
    quote_source_hint,
    yfinance_snapshots,
)
from .parser import parse_watchlist_detailed
from .state import DayState, StateStore, trading_date
from .t212_client import T212Client, currency_symbol
from .trader import Trader

load_dotenv()

app = Flask(__name__, template_folder="templates")
settings = Settings.from_env()

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s %(levelname)s %(message)s",
)

store = StateStore(settings.state_dir)
trader = Trader(settings)

_AUTO_RESUME = os.getenv("AUTO_RESUME_TRADING", "true").lower() == "true"
_resume_lock = threading.Lock()
_resume_done = False
_prefetch_lock = threading.Lock()
_prefetch_running = False


def _schedule_reference_prefetch(setups) -> None:
    """Yahoo ref-prijzen op achtergrond — nooit synchroon op page load."""
    global _prefetch_running
    if not setups:
        return
    tickers = [s.ticker for s in setups]
    with _prefetch_lock:
        if _prefetch_running:
            return
        _prefetch_running = True

    def _run() -> None:
        global _prefetch_running
        try:
            prefetch_reference_prices(tickers)
        finally:
            with _prefetch_lock:
                _prefetch_running = False

    threading.Thread(target=_run, daemon=True, name="ref-prefetch").start()


def _build_live_quotes(setups, *, engine_live: bool) -> list:
    data_source = settings.effective_data_source()
    if not setups:
        return []
    try:
        if data_source == "yfinance":
            rows = yfinance_snapshots(setups, settings, today())
            for r in rows:
                r.setdefault("followed", True)
                r.setdefault("exclude_reason", "")
                if r.get("last") is not None:
                    r["last_source"] = "live"
        elif engine_live:
            rows = trader.get_live_quotes(setups)
        else:
            rows = apply_follow_status(
                placeholder_snapshots(setups),
                trader.get_follow_status(setups),
            )
        _schedule_reference_prefetch(setups)
        return enrich_quotes_with_reference(rows, fetch_missing=False)
    except Exception as exc:
        logging.warning("Live quotes mislukt: %s", exc)
        return []


def _launch_trader(state: DayState, *, reason: str) -> None:
    if not trader.start(state):
        state.active = False
        store.save(state)
        logging.warning("Trader start mislukt (%s) — state terug op inactief.", reason)
        return
    state.active = True
    state.crashed = False
    store.save(state)
    logging.info("Trader opgestart (%s).", reason)


def _maybe_auto_resume() -> None:
    global _resume_done
    with _resume_lock:
        if _resume_done:
            return
        _resume_done = True
    if not _AUTO_RESUME:
        logging.info("AUTO_RESUME_TRADING=false — geen auto-hervat na boot.")
        return
    state = store.load(trading_date(), settings.paper_capital)
    if not state.active or not state.get_setups():
        return
    if trader.is_engine_live():
        return
    _launch_trader(state, reason="auto-resume na boot")


def _schedule_auto_resume() -> None:
    threading.Thread(target=_maybe_auto_resume, daemon=True, name="auto-resume").start()


_schedule_auto_resume()


def today() -> date:
    return trading_date()


def load_state(*, refresh_cash: bool = True) -> DayState:
    state = store.load(today(), settings.paper_capital)
    if (
        refresh_cash
        and settings.effective_broker() == "t212"
        and not trader.is_engine_live()
    ):
        try:
            from .t212_client import T212Client, T212RateLimitError

            if isinstance(trader.client, T212Client):
                trader.client._ensure_connected()
                actual_cash = trader.client.get_cash(force=True)
                if actual_cash >= 0:
                    store.update_cash(state, actual_cash)
        except T212RateLimitError:
            logging.debug("T212 cash refresh overgeslagen — rate limit.")
        except Exception as exc:
            logging.warning("T212 cash ophalen mislukt: %s", exc)
    elif state.cash <= 0:
        store.update_cash(state, settings.paper_capital)
    return state


def _broker_label() -> str:
    broker = settings.effective_broker()
    if broker == "t212":
        mode = "DEMO" if settings.t212_demo else "LIVE"
        return f"T212 {mode}"
    return "PAPER"


def _render_ctx(state: DayState, *, error: str = "", warn_blocked: list | None = None) -> dict:
    setups = state.get_setups()
    trades = state.get_closed_trades()
    positions = state.get_positions()
    day_pnl = sum(t.pnl for t in trades)
    engine_live = trader.is_engine_live()
    bot_status = "inactief"
    bot_hint = ""
    if state.crashed and not engine_live:
        bot_status = "gecrasht"
        bot_hint = "Trading-loop is onverwacht gestopt. Controleer logs en start opnieuw."
    elif state.active and engine_live:
        bot_status = "handelt"
    elif state.active:
        bot_status = "actief_zonder_engine"
        bot_hint = (
            "Opdracht ACTIEF in state, maar engine draait niet. Stop → Start, "
            "of wacht op auto-resume."
        )

    data_source = settings.effective_data_source()
    live_quotes = _build_live_quotes(setups, engine_live=engine_live)
    quote_by_ticker = {q["ticker"]: q for q in live_quotes}
    for t in warn_blocked or []:
        quote_by_ticker.setdefault(t, {
            "ticker": t,
            "followed": False,
            "exclude_reason": "Niet verhandelbaar op T212",
            "status": "Niet verhandelbaar op T212",
            "last": None,
        })
    excluded_tickers = sorted({
        q["ticker"]
        for q in quote_by_ticker.values()
        if not q.get("followed", True)
    })

    is_paper_broker = settings.effective_broker() == "paper"
    account_currency = "USD"
    if settings.effective_broker() == "t212" and isinstance(trader.client, T212Client):
        account_currency = trader.client.get_account_currency_cached(default="EUR")
    account_currency_symbol = currency_symbol(account_currency)

    return dict(
        state=state,
        setups=setups,
        trades=trades,
        positions=positions,
        day_pnl=day_pnl,
        today=today().isoformat(),
        data_source=data_source,
        quote_source_hint=quote_source_hint(data_source, engine_live=engine_live),
        broker_label=_broker_label(),
        is_paper_broker=is_paper_broker,
        error=error,
        warn_blocked=warn_blocked or [],
        warn_skipped=0,
        excluded_tickers=excluded_tickers,
        live_quotes=live_quotes,
        quote_by_ticker=quote_by_ticker,
        volume_mult=settings.volume_mult,
        orb_minutes=settings.orb_minutes,
        engine_live=engine_live,
        bot_status=bot_status,
        bot_hint=bot_hint,
        account_currency=account_currency,
        account_currency_symbol=account_currency_symbol,
        stock_currency_symbol="$",
    )


def _active_state() -> DayState:
    """State uit draaiende engine, anders van schijf."""
    if trader.is_engine_live() and trader._state is not None:
        return trader._state
    return load_state(refresh_cash=False)


@app.route("/")
def index():
    warn = [t.strip().upper() for t in request.args.get("warn_blocked", "").split(",") if t.strip()]
    err = request.args.get("error", "").strip()
    # Geen sync T212 op page load als bot draait — voorkomt lock/rate-limit hang.
    ctx = _render_ctx(_active_state(), warn_blocked=warn, error=err)
    skipped = request.args.get("warn_skipped")
    if skipped and skipped.isdigit():
        ctx["warn_skipped"] = int(skipped)
    else:
        ctx["warn_skipped"] = 0
    return render_template("index.html", **ctx)


@app.route("/upload", methods=["POST"])
def upload():
    if trader.is_engine_live():
        ctx = _render_ctx(
            load_state(),
            error="Stop de bot eerst voordat je de watchlist wijzigt.",
        )
        return render_template("index.html", **ctx)

    text = request.form.get("watchlist", "")
    result = parse_watchlist_detailed(text)
    setups = result.setups
    if not setups:
        ctx = _render_ctx(load_state(), error="Geen geldige setups gevonden.")
        return render_template("index.html", **ctx)

    state = load_state()
    store.set_setups(state, setups)
    logging.info("Watchlist: %d setups (%d rijen genegeerd)", len(setups), result.skipped)

    blocked: list[str] = []
    for s in setups:
        try:
            if not trader.client.is_tradable(s.ticker):
                blocked.append(s.ticker)
        except Exception:
            blocked.append(s.ticker)

    if blocked:
        return redirect(url_for("index", warn_blocked=",".join(blocked)))
    if result.skipped > 0:
        return redirect(url_for("index", warn_skipped=str(result.skipped)))
    return redirect(url_for("index"))


@app.route("/start", methods=["POST"])
def start():
    state = load_state()
    if not state.get_setups():
        return jsonify({"error": "Geen watchlist geladen"}), 400
    threading.Thread(
        target=_launch_trader,
        args=(state,),
        kwargs={"reason": "dashboard start"},
        daemon=True,
    ).start()
    return redirect(url_for("index"))


@app.route("/stop", methods=["POST"])
def stop():
    trader.stop()
    state = load_state()
    state.active = False
    state.crashed = False
    store.save(state)
    return redirect(url_for("index"))


@app.route("/position/<ticker>/update", methods=["POST"])
def update_position(ticker: str):
    """Stop (hold) van een open positie live bijwerken — winst vastzetten."""
    ticker = ticker.strip().upper()
    state = _active_state()

    if ticker not in state.positions:
        return redirect(url_for("index", error=f"Geen open positie voor {ticker}."))

    raw_hold = request.form.get("hold", "").strip()
    try:
        new_hold = float(raw_hold)
    except ValueError:
        return redirect(url_for("index", error=f"Ongeldige stop-prijs voor {ticker}."))

    pos = state.positions[ticker]
    target = float(pos["target_price"])

    if new_hold <= 0:
        return redirect(url_for("index", error="Stop moet groter dan 0 zijn."))
    if new_hold >= target:
        return redirect(
            url_for(
                "index",
                error=f"Stop ${new_hold:.2f} moet onder T1 ${target:.2f} blijven.",
            )
        )

    old_hold = float(pos.get("stop_price", 0))
    pos["stop_price"] = round(new_hold, 4)
    store.save(state)
    logging.info(
        "Stop %s bijgewerkt via dashboard: $%.4f → $%.4f (T1=$%.2f)",
        ticker, old_hold, new_hold, target,
    )
    return redirect(url_for("index"))


@app.route("/capital", methods=["POST"])
def set_capital():
    if settings.effective_broker() == "t212":
        return jsonify({"error": "Kapitaal wordt beheerd door Trading 212, niet lokaal."}), 400

    try:
        amount = float(request.form.get("capital", 0))
        if amount <= 0:
            raise ValueError("Kapitaal moet positief zijn")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    state = load_state()
    if state.active:
        return jsonify({"error": "Stop de bot eerst"}), 400

    store.update_cash(state, amount)
    trader.client.bind_state(store, state)
    return redirect(url_for("index"))


@app.route("/history")
def history():
    days = []
    for d in store.list_trade_dates():
        summary = store.day_summary(d)
        if summary:
            days.append(summary)
    return render_template(
        "history.html",
        days=days,
        today=today().isoformat(),
        state_dir_hint=settings.state_dir,
    )


@app.route("/history/<date_str>")
def history_day(date_str: str):
    try:
        trade_date = date.fromisoformat(date_str)
    except ValueError:
        abort(404)
    state = store.load_date(trade_date, settings.paper_capital)
    if state is None:
        return render_template(
            "history_day.html",
            date_str=date_str,
            trades=[],
            day_pnl=0.0,
            cash=0.0,
            missing=True,
            today=today().isoformat(),
        )
    trades = state.get_closed_trades()
    day_pnl = sum(t.pnl for t in trades)
    return render_template(
        "history_day.html",
        date_str=date_str,
        trades=trades,
        day_pnl=day_pnl,
        cash=state.cash,
        missing=False,
        today=today().isoformat(),
    )


@app.route("/status")
def status():
    state = load_state()
    return jsonify({
        "date": state.trade_date,
        "active": state.active,
        "crashed": state.crashed,
        "engine_live": trader.is_engine_live(),
        "data_source": settings.effective_data_source(),
        "broker": _broker_label(),
        "setups": len(state.setups),
        "positions": len(state.positions),
        "trades": len(state.closed_trades),
        "day_pnl": sum(t["pnl"] for t in state.closed_trades),
        "cash": state.cash,
    })


@app.get("/health")
def health():
    """K8s liveness/readiness — altijd 200 zolang Flask draait.

    De trading-engine kan uit staan (AUTO_RESUME=false, handmatige stop);
    het dashboard moet dan nog bereikbaar blijven. Gebruik /status voor
    engine-state en monitoring.
    """
    state = load_state(refresh_cash=False)
    engine_live = trader.is_engine_live()
    issues = []
    if state.crashed:
        issues.append("engine_crashed")
    elif state.active and not engine_live:
        issues.append("engine_not_running")
    return jsonify({
        "status": "degraded" if issues else "ok",
        "issues": issues,
        "engine_live": engine_live,
    })


def _prefetch_on_boot() -> None:
    try:
        state = store.load(trading_date(), settings.paper_capital)
        setups = state.get_setups()
        if setups:
            _schedule_reference_prefetch(setups)
    except Exception as exc:
        logging.debug("Ref-prefetch bij boot overgeslagen: %s", exc)


_prefetch_on_boot()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=settings.dashboard_port,
        debug=False,
        threaded=True,
    )
