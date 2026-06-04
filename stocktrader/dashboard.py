"""
Flask dashboard — watchlist uploaden en bot beheren.

Start: python -m stocktrader.dashboard
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from .config import Settings
from .parser import format_setups, parse_watchlist
from .state import StateStore, DayState, trading_date
from .market_snapshot import live_snapshots
from .trader import Trader

load_dotenv()

app      = Flask(__name__, template_folder="templates")
settings = Settings.from_env()

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s %(levelname)s %(message)s",
)

store    = StateStore(settings.state_dir)
trader   = Trader(settings)

_AUTO_RESUME = os.getenv("AUTO_RESUME_TRADING", "true").lower() == "true"
_resume_lock = threading.Lock()
_resume_done = False


def _launch_trader(state: DayState, *, reason: str) -> None:
    state.active = True
    store.save(state)
    trader.start(state)
    logging.info("Trader opgestart (%s).", reason)


def _maybe_auto_resume() -> None:
    """Na pod-restart: hervat trading als state.active en watchlist aanwezig.
    Probeert tot 3x met 30s interval als IBKR nog niet verbonden is."""
    global _resume_done
    with _resume_lock:
        if _resume_done:
            return
        _resume_done = True
    if not _AUTO_RESUME:
        logging.info("AUTO_RESUME_TRADING=false — geen auto-hervat na boot.")
        return
    state = store.load(today(), settings.paper_capital)
    if not state.active or not state.get_setups():
        return
    if trader.is_engine_live():
        logging.info("Auto-resume: engine draait al.")
        return

    _MAX_RESUME_TRIES = 3
    _RESUME_WAIT_SEC  = 30
    for attempt in range(1, _MAX_RESUME_TRIES + 1):
        if not settings.paper_mode:
            deadline = time.time() + 45
            while time.time() < deadline:
                try:
                    connected = trader.ibkr.is_connected()
                    balances  = trader.ibkr.get_cash_balances() if connected else {}
                except Exception:
                    connected, balances = False, {}
                if connected and balances:
                    break
                time.sleep(2)
        if trader.is_engine_live():
            logging.info("Auto-resume: engine draait al (poging %d).", attempt)
            return
        state = store.load(today(), settings.paper_capital)
        if not state.active or not state.get_setups():
            logging.info("Auto-resume: state niet meer actief — stoppen.")
            return
        try:
            _launch_trader(state, reason=f"auto-resume poging {attempt}/{_MAX_RESUME_TRIES}")
            return
        except Exception as exc:
            logging.error("Auto-resume poging %d mislukt: %s", attempt, exc)
            if attempt < _MAX_RESUME_TRIES:
                time.sleep(_RESUME_WAIT_SEC)
    logging.error("Auto-resume mislukt na %d pogingen.", _MAX_RESUME_TRIES)


def _schedule_auto_resume() -> None:
    threading.Thread(target=_maybe_auto_resume, daemon=True, name="auto-resume").start()


_schedule_auto_resume()


def today() -> date:
    return trading_date()  # altijd ET, niet server-TZ


def ibkr_cash_info() -> dict:
    """IBKR cash per valuta + welke de bot voor sizing gebruikt."""
    if settings.paper_mode:
        return {}
    try:
        balances = trader.ibkr.get_cash_balances()
        amount, currency = trader.ibkr.get_trading_cash()
        if not balances and amount <= 0:
            return {}
        return {
            "balances": balances,
            "balance_rows": sorted(balances.items()),
            "trading_amount": amount,
            "trading_currency": currency,
        }
    except Exception:
        return {}


def load_state(*, sync_ibkr: bool = True) -> DayState:
    state = store.load(today(), settings.paper_capital)
    if settings.tracked_capital and not settings.paper_mode:
        if state.cash <= 0:
            store.update_cash(state, settings.paper_capital)
    elif not settings.paper_mode and not settings.tracked_capital:
        try:
            amount, _cur = trader.ibkr.get_trading_cash()
            if amount > 0:
                state.cash = amount
        except Exception:
            pass
        if sync_ibkr and ibkr_connected() and state.get_setups():
            try:
                imported = trader.sync_ibkr_positions(state, notify=False)
                if imported:
                    logging.info(
                        "Dashboard: IBKR posities geïmporteerd: %s", ", ".join(imported),
                    )
            except Exception as exc:
                logging.warning("Dashboard IBKR sync mislukt: %s", exc)
    return state


def ibkr_connected() -> bool:
    if settings.paper_mode:
        return False
    try:
        return trader.ibkr.is_connected()
    except Exception:
        return False


@app.route("/")
def index():
    state     = load_state()
    setups    = state.get_setups()
    trades    = state.get_closed_trades()
    positions = state.get_positions()
    day_pnl   = sum(t.pnl for t in trades)
    warn_blocked = [t for t in request.args.get("warn_blocked", "").split(",") if t]
    cash_info = ibkr_cash_info()
    sizing_note = ""
    if not settings.paper_mode:
        if settings.tracked_capital:
            sizing_note = (
                f"Bot sized op ingesteld kapitaal (${state.cash:.2f}), niet op IB-wallet."
            )
        elif cash_info:
            cur = cash_info.get("trading_currency", "USD")
            amt = cash_info.get("trading_amount", 0)
            sizing_note = (
                f"Bot sized op {cur} ${amt:.2f} (US-aandelen; USD heeft voorrang op EUR)."
            )

    live_quotes: list = []
    quote_by_ticker: dict = {}
    if not settings.paper_mode and setups and ibkr_connected():
        try:
            live_quotes = live_snapshots(setups, settings, today())
            quote_by_ticker = {q["ticker"]: q for q in live_quotes}
        except Exception as exc:
            logging.warning("Live snapshot mislukt: %s", exc)

    engine_live = trader.is_engine_live()
    bot_status = "inactief"
    bot_hint = ""
    if state.active and engine_live:
        bot_status = "handelt"
    elif state.active:
        bot_status = "actief_zonder_engine"
        bot_hint = (
            "Opdracht ACTIEF in state, maar trading-engine draait niet "
            "(vaak na pod-restart). Stop → Start, of wacht op auto-resume."
        )

    return render_template(
        "index.html",
        state=state,
        setups=setups,
        trades=trades,
        positions=positions,
        day_pnl=day_pnl,
        today=today().isoformat(),
        paper_mode=settings.paper_mode,
        tracked_capital=settings.tracked_capital,
        ibkr_cash=cash_info,
        sizing_note=sizing_note,
        ibkr_connected=ibkr_connected(),
        warn_blocked=warn_blocked,
        live_quotes=live_quotes,
        quote_by_ticker=quote_by_ticker,
        volume_mult=settings.volume_mult,
        orb_minutes=settings.orb_minutes,
        engine_live=engine_live,
        bot_status=bot_status,
        bot_hint=bot_hint,
    )


@app.route("/upload", methods=["POST"])
def upload():
    text   = request.form.get("watchlist", "")
    setups = parse_watchlist(text)

    if not setups:
        return render_template("index.html",
            error="Geen geldige setups gevonden. Controleer het formaat.",
            state=load_state(), setups=[], trades=[], positions={},
            day_pnl=0, today=today().isoformat(), paper_mode=settings.paper_mode,
            tracked_capital=settings.tracked_capital,             ibkr_cash={},
            sizing_note="",
            ibkr_connected=ibkr_connected(), warn_blocked=[],
        )

    state = load_state()
    store.set_setups(state, setups)
    logging.info("Watchlist geüpload: %d setups — %s", len(setups), ", ".join(s.ticker for s in setups))

    blocked: list[str] = []
    if not settings.paper_mode:
        for s in setups:
            try:
                if not trader.ibkr.is_tradable(s.ticker):
                    blocked.append(s.ticker)
            except Exception:
                blocked.append(s.ticker)
        if blocked:
            logging.warning("IBKR check bij upload — geblokkeerd: %s", blocked)

    if blocked:
        return redirect(url_for("index", warn_blocked=",".join(blocked)))
    return redirect(url_for("index"))


@app.route("/start", methods=["POST"])
def start():
    state = load_state()
    if not state.get_setups():
        return jsonify({"error": "Geen watchlist geladen"}), 400
    threading.Thread(
        target=_launch_trader, args=(state,), kwargs={"reason": "dashboard start"},
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


@app.route("/sync-positions", methods=["POST"])
def sync_positions():
    """Haal open IBKR-posities op en koppel aan watchlist (stop/T1 uit setup)."""
    if settings.paper_mode:
        return jsonify({"error": "Alleen in IBKR-modus"}), 400
    state = load_state(sync_ibkr=False)
    if not state.get_setups():
        return jsonify({"error": "Eerst watchlist laden"}), 400
    if not ibkr_connected():
        return jsonify({"error": "IBKR niet verbonden"}), 400
    imported = trader.sync_ibkr_positions(state, notify=True)
    if not imported:
        return redirect(url_for("index"))
    return redirect(url_for("index"))


@app.route("/capital", methods=["POST"])
def set_capital():
    """Stel het startkapitaal in voor vandaag."""
    try:
        amount = float(request.form.get("capital", 0))
        if amount <= 0:
            raise ValueError("Kapitaal moet positief zijn")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    state = load_state()
    if state.active:
        return jsonify({"error": "Stop de bot eerst voordat je het kapitaal aanpast"}), 400

    store.update_cash(state, amount)
    logging.info("Kapitaal ingesteld op $%.2f", amount)
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
        "date":           state.trade_date,
        "active":         state.active,
        "engine_live":    trader.is_engine_live(),
        "ibkr_connected": ibkr_connected(),
        "setups":         len(state.setups),
        "positions":      len(state.positions),
        "trades":         len(state.closed_trades),
        "day_pnl":        sum(t["pnl"] for t in state.closed_trades),
        "cash":           state.cash,
    })


@app.get("/health")
def health():
    state = load_state(sync_ibkr=False)
    engine_live   = trader.is_engine_live()
    ibkr_ok       = ibkr_connected()
    zombie_active = state.active and not engine_live  # state zegt actief maar engine draait niet

    issues = []
    if zombie_active:
        issues.append("engine_not_running")
    if state.active and not ibkr_ok and not settings.paper_mode:
        issues.append("ibkr_disconnected")

    if issues:
        return jsonify({
            "status":      "degraded",
            "issues":      issues,
            "engine_live": engine_live,
            "ibkr":        ibkr_ok,
        }), 200  # 200 zodat k8s liveness slaagt; aparte readiness kan 503 geven

    return jsonify({"status": "ok", "engine_live": engine_live})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.dashboard_port, debug=False)
