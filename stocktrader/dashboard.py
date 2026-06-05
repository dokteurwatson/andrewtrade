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
from .market_snapshot import live_snapshots
from .parser import parse_watchlist
from .state import DayState, StateStore, trading_date
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


def _launch_trader(state: DayState, *, reason: str) -> None:
    state.active = True
    store.save(state)
    trader.start(state)
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


def load_state() -> DayState:
    state = store.load(today(), settings.paper_capital)
    if settings.effective_broker() == "t212":
        try:
            actual_cash = trader.client.get_cash()
            if actual_cash > 0:
                store.update_cash(state, actual_cash)
        except Exception as exc:
            logging.warning("T212 cash ophalen mislukt: %s", exc)
            if state.cash <= 0:
                store.update_cash(state, settings.paper_capital)
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
    if state.active and engine_live:
        bot_status = "handelt"
    elif state.active:
        bot_status = "actief_zonder_engine"
        bot_hint = (
            "Opdracht ACTIEF in state, maar engine draait niet. Stop → Start, "
            "of wacht op auto-resume."
        )

    live_quotes: list = []
    quote_by_ticker: dict = {}
    if setups:
        try:
            live_quotes = live_snapshots(setups, settings, today())
            quote_by_ticker = {q["ticker"]: q for q in live_quotes}
        except Exception as exc:
            logging.warning("Live snapshot mislukt: %s", exc)

    is_paper_broker = settings.effective_broker() == "paper"

    return dict(
        state=state,
        setups=setups,
        trades=trades,
        positions=positions,
        day_pnl=day_pnl,
        today=today().isoformat(),
        data_source=settings.effective_data_source(),
        broker_label=_broker_label(),
        is_paper_broker=is_paper_broker,
        error=error,
        warn_blocked=warn_blocked or [],
        live_quotes=live_quotes,
        quote_by_ticker=quote_by_ticker,
        volume_mult=settings.volume_mult,
        orb_minutes=settings.orb_minutes,
        engine_live=engine_live,
        bot_status=bot_status,
        bot_hint=bot_hint,
    )


@app.route("/")
def index():
    warn = [t for t in request.args.get("warn_blocked", "").split(",") if t]
    return render_template("index.html", **_render_ctx(load_state(), warn_blocked=warn))


@app.route("/upload", methods=["POST"])
def upload():
    text = request.form.get("watchlist", "")
    setups = parse_watchlist(text)
    if not setups:
        ctx = _render_ctx(load_state(), error="Geen geldige setups gevonden.")
        return render_template("index.html", **ctx)

    state = load_state()
    store.set_setups(state, setups)
    logging.info("Watchlist: %d setups", len(setups))

    blocked: list[str] = []
    for s in setups:
        try:
            if not trader.client.is_tradable(s.ticker):
                blocked.append(s.ticker)
        except Exception:
            blocked.append(s.ticker)

    if blocked:
        return redirect(url_for("index", warn_blocked=",".join(blocked)))
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
    store.save(state)
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
    state = load_state()
    engine_live = trader.is_engine_live()
    issues = []
    if state.active and not engine_live:
        issues.append("engine_not_running")
    if issues:
        return jsonify({
            "status": "degraded",
            "issues": issues,
            "engine_live": engine_live,
        }), 200
    return jsonify({"status": "ok", "engine_live": engine_live})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.dashboard_port, debug=False)
