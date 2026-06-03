"""
Flask dashboard — watchlist uploaden en bot beheren.

Start: python -m stocktrader.dashboard
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for

from .config import Settings
from .parser import format_setups, parse_watchlist
from .state import StateStore, DayState
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


def today() -> date:
    return date.today()


def load_state() -> DayState:
    state = store.load(today(), settings.paper_capital)
    # In IBKR mode: haal echt saldo op
    if not settings.paper_mode:
        try:
            state.cash = trader.ibkr.get_cash()
        except Exception:
            pass  # IBKR niet verbonden → fallback naar opgeslagen waarde
    return state


@app.route("/")
def index():
    state     = load_state()
    setups    = state.get_setups()
    trades    = state.get_closed_trades()
    positions = state.get_positions()
    day_pnl   = sum(t.pnl for t in trades)

    return render_template(
        "index.html",
        state=state,
        setups=setups,
        trades=trades,
        positions=positions,
        day_pnl=day_pnl,
        today=today().isoformat(),
        paper_mode=settings.paper_mode,
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
        )

    state = load_state()
    store.set_setups(state, setups)
    logging.info("Watchlist geüpload: %d setups", len(setups))
    return redirect(url_for("index"))


@app.route("/start", methods=["POST"])
def start():
    state = load_state()
    if not state.get_setups():
        return jsonify({"error": "Geen watchlist geladen"}), 400
    state.active = True
    store.save(state)
    threading.Thread(target=trader.start, args=(state,), daemon=True).start()
    logging.info("Trader gestart via dashboard.")
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


@app.route("/status")
def status():
    state = load_state()
    return jsonify({
        "date":      state.trade_date,
        "active":    state.active,
        "setups":    len(state.setups),
        "positions": len(state.positions),
        "trades":    len(state.closed_trades),
        "day_pnl":   sum(t["pnl"] for t in state.closed_trades),
        "cash":      state.cash,
    })


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.dashboard_port, debug=False)
