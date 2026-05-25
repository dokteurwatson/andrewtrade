const CONFIG_META = {
  sma_period:                          { label: "SMA Period",                    tip: "Trend filter: prijs moet boven het gemiddelde van de laatste N candles liggen voor een entry." },
  rsi_period:                          { label: "RSI Period",                    tip: "Aantal candles voor RSI berekening. RSI(2) = zeer gevoelig, reageert snel op oversold/overbought." },
  rsi_entry_threshold:                 { label: "RSI Entry Threshold",           tip: "RSI moet onder deze waarde zakken voor een koopsignaal. Default 20 = extreem oversold." },
  rsi_exit_threshold:                  { label: "RSI Exit Threshold",            tip: "RSI moet boven deze waarde komen om te verkopen. Default 70 = overbought." },
  timeframe:                           { label: "Timeframe",                     tip: "Candle interval. 4h = elke 4 uur een nieuwe candle en potentieel een nieuw signaal." },
  candle_limit:                        { label: "Candle Limit",                  tip: "Aantal candles dat wordt opgehaald van Kraken per cycle. Meer = betere SMA berekening." },
  start_capital_usd:                   { label: "Start Capital",                 tip: "Startbedrag in USD voor de paper trading simulatie." },
  min_order_usd:                       { label: "Min Order USD",                 tip: "Minimale ordergrootte. Orders kleiner dan dit bedrag worden geskipt." },
  slippage_rate:                       { label: "Slippage Rate",                 tip: "Gesimuleerde slippage per trade (0.0005 = 0.05%). Simuleert realistische marktorder uitvoering." },
  taker_fee_rate:                      { label: "Taker Fee",                     tip: "Kraken taker fee per trade (0.0026 = 0.26%). Wordt van elke entry en exit afgetrokken." },
  risk_threshold_balance:              { label: "Risk Threshold",                tip: "Onder dit bedrag gaat de bot all-in per trade. Erboven gebruikt hij risk-based sizing." },
  position_sizing_below_threshold:     { label: "Sizing Below Threshold",        tip: "Hoe de bot positie berekent als saldo onder de threshold zit. 'all_in' = alles inzetten." },
  risk_per_trade_above_threshold:      { label: "Risk Per Trade (above)",        tip: "Percentage van equity dat geriskeerd wordt per trade als saldo boven threshold zit." },
  stop_loss_pct_above_threshold:       { label: "Stop Loss %",                   tip: "Stop-loss afstand onder entry prijs. Alleen actief boven de risk threshold." },
  max_daily_loss_above_threshold:      { label: "Max Daily Loss",                tip: "Maximaal dagverlies als % van equity. Bot stopt met entries als dit bereikt wordt." },
  max_open_positions_above_threshold:  { label: "Max Open Positions",            tip: "Maximaal aantal gelijktijdige posities boven de threshold." },
  max_consecutive_losses_above_threshold: { label: "Max Consecutive Losses",    tip: "Na dit aantal verliezende trades op rij gaat de bot in cooldown." },
  cooldown_candles_after_limit:        { label: "Cooldown Candles",              tip: "Aantal candles dat de bot wacht na het bereiken van het max verliezende trades limiet." },
  poll_seconds:                        { label: "Poll Interval (s)",             tip: "Hoe vaak de bot de markt checkt in seconden. Default 60s." },
  bugatti_target_usd:                  { label: "Bugatti Target",                tip: "Doelbedrag voor de Bugatti meter. Default $2.000.000." },
  mode:                                { label: "Mode",                          tip: "paper = gesimuleerd handelen zonder echt geld. live = echte orders (nog niet actief)." },
  exchange_id:                         { label: "Exchange",                      tip: "Beurs waar data vandaan komt en straks live gehandeld wordt." },
  coin_list:                           { label: "Coins",                         tip: "Coins die de bot monitort en op handelt." },
};

function renderConfig(cfg) {
  const grid = document.getElementById("configGrid");
  if (!grid) return;
  grid.innerHTML = Object.entries(cfg).map(([key, val]) => {
    const meta = CONFIG_META[key] || { label: key, tip: "" };
    const display = Array.isArray(val) ? val.join(", ") : String(val);
    return `<div class="config-item">
      <div class="config-label">${meta.label}</div>
      <div class="config-value">${display}</div>
      <div class="config-tooltip">${meta.tip}</div>
    </div>`;
  }).join("");
}


let candleSeries;
let smaSeries;
let chartEnabled = false;

function createSeries(chartInstance, typeName, options) {
  const legacyMethod = `add${typeName}Series`;
  if (typeof chartInstance[legacyMethod] === "function") {
    return chartInstance[legacyMethod](options);
  }

  if (typeof chartInstance.addSeries === "function" && window.LightweightCharts) {
    const seriesType = window.LightweightCharts[`${typeName}Series`] || typeName;
    return chartInstance.addSeries(seriesType, options);
  }

  return null;
}

function fmtMoney(value) {
  return `$${Number(value || 0).toFixed(2)}`;
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = value;
  }
}

function fillTable(bodyId, rows, colCount, emptyLabel) {
  const body = document.getElementById(bodyId);
  if (!body) return;
  body.innerHTML = rows.length ? rows.join("") : `<tr><td colspan='${colCount}'>${emptyLabel}</td></tr>`;
}

function initChart() {
  const chartEl = document.getElementById("chart");
  try {
    if (!window.LightweightCharts || !chartEl) {
      if (chartEl) {
        chartEl.innerHTML = "<div style='padding:12px;color:#7a6854'>Chart library unavailable. Dashboard data is still live.</div>";
      }
      return;
    }

    chart = LightweightCharts.createChart(chartEl, {
      layout: {
        background: { color: "#fffdf9" },
        textColor: "#4a3f34",
      },
      grid: {
        vertLines: { color: "#f0e0cf" },
        horzLines: { color: "#f0e0cf" },
      },
      width: chartEl.clientWidth,
      height: 420,
      rightPriceScale: { borderColor: "#d8c3ab" },
      timeScale: { borderColor: "#d8c3ab" },
    });

    candleSeries = createSeries(chart, "Candlestick", {
        upColor: "#2b8c4a",
        downColor: "#b13d32",
        borderVisible: false,
        wickUpColor: "#2b8c4a",
        wickDownColor: "#b13d32",
      });

    smaSeries = createSeries(chart, "Line", {
        color: "#c3512f",
        lineWidth: 2,
      });

    if (candleSeries && smaSeries) {
      chartEnabled = true;
    } else {
      chartEl.innerHTML = "<div style='padding:12px;color:#7a6854'>Chart API variant not supported in this browser build.</div>";
      chartEnabled = false;
    }

    window.addEventListener("resize", () => {
      if (chart) {
        chart.applyOptions({ width: chartEl.clientWidth });
      }
    });
  } catch (err) {
    chartEnabled = false;
    if (chartEl) {
      chartEl.innerHTML = "<div style='padding:12px;color:#7a6854'>Chart init failed, dashboard data still active.</div>";
    }
    setText("meta", "Chart init failed; data widgets still updating.");
  }
}

async function loadChart(symbol) {
  if (!chartEnabled) return;
  const response = await fetch(`/api/chart?symbol=${encodeURIComponent(symbol)}&limit=350`);
  if (!response.ok) {
    return;
  }
  const data = await response.json();
  const projection = data.projection || {};

  candleSeries.setData(projection.candles || []);
  smaSeries.setData(projection.sma || []);
  if (typeof candleSeries.setMarkers === "function") {
    candleSeries.setMarkers(projection.markers || []);
  } else if (typeof LightweightCharts.createSeriesMarkers === "function") {
    LightweightCharts.createSeriesMarkers(candleSeries, projection.markers || []);
  }
}

async function loadDashboard() {
  try {
    const response = await fetch("/api/dashboard");
    if (!response.ok) {
      setText("meta", `Dashboard API error: ${response.status}`);
      return;
    }
    const data = await response.json();

    const exchangeLabel = (data.meta?.exchange || "unknown").toUpperCase();
    const timeframeLabel = data.meta?.timeframe || "?";
    const coins = data.meta?.coins || [];
    setText("meta", `${exchangeLabel} | ${timeframeLabel} | ${coins.join(", ")}`);
    setText("cash", fmtMoney(data.wallet.cash_usd));
    setText("cooldown", `Cooldown candles left: ${data.wallet.cooldown_remaining}`);
    setText("openPositions", String(data.stats.open_positions));
    setText("entries", `Entries: ${data.stats.entries} | Exits: ${data.stats.exits}`);
    setText("potentialScore", `${Number(data.trade_potential.portfolio_score || 0).toFixed(2)}%`);
    setText("potentialState", `State: ${data.trade_potential.portfolio_state}`);

    fillTable(
    "ongoingBody",
    (data.ongoing_positions || []).map(
      (row) => `<tr><td>${row.symbol}</td><td>${Number(row.quantity).toFixed(6)}</td><td>${Number(row.entry_price).toFixed(6)}</td><td>${Number(row.stop_price).toFixed(6)}</td></tr>`
    ),
    4,
    "No ongoing positions"
  );

    fillTable(
    "completedBody",
    (data.completed_trades || []).slice(0, 20).map((row) => {
      const pnl = Number(row.pnl || 0);
      const klass = pnl >= 0 ? "good" : "bad";
      return `<tr><td>${row.symbol || "-"}</td><td class="${klass}">${pnl.toFixed(4)}</td><td>${Number(row.price || 0).toFixed(6)}</td><td>${row.reason || "-"}</td></tr>`;
    }),
    4,
    "No completed trades yet"
  );

    fillTable(
    "potentialBody",
    (data.trade_potential.candidates || []).map((row) => {
      const stateClass = row.state === "entry_ready" ? "good pulse" : row.state === "trend_not_ready" ? "bad" : "";
      return `<tr><td>${row.symbol}</td><td>${Number(row.score).toFixed(2)}%</td><td class="${stateClass}">${row.state}</td><td>${Number(row.rsi).toFixed(2)}</td><td>${row.trend_ok ? "uptrend" : "off"}</td></tr>`;
    }),
    5,
    "No potential data"
  );

    const selector = document.getElementById("chartSymbol");
    if (!selector.dataset.initialized) {
      selector.innerHTML = "";
      (coins || []).forEach((coin) => {
        const symbol = `${coin}/USD`;
        const option = document.createElement("option");
        option.value = symbol;
        option.textContent = symbol;
        selector.appendChild(option);
      });
      selector.dataset.initialized = "1";
      selector.addEventListener("change", () => loadChart(selector.value));
    }

    const fallbackSymbol = coins.length ? `${coins[0]}/USD` : "";
    const selectedSymbol = selector.value || fallbackSymbol;
    if (!selector.value && selectedSymbol) {
      selector.value = selectedSymbol;
    }
    if (selectedSymbol) {
      loadChart(selectedSymbol);
    }
  } catch (err) {
    setText("meta", "Dashboard load failed. Check browser console.");
  }
}

async function loadConfig() {
  try {
    const resp = await fetch("/api/config");
    if (!resp.ok) return;
    const cfg = await resp.json();
    renderConfig(cfg);
    const badge = document.getElementById("modeLabel");
    if (badge) {
      const isPaper = (cfg.mode || "paper") === "paper";
      badge.textContent = isPaper ? "PAPER TRADING — Simulated" : "LIVE TRADING — Real Money";
      badge.className = "mode-badge " + (isPaper ? "paper" : "live");
    }
  } catch (_) {}
}

initChart();
loadDashboard();
loadConfig();
setInterval(loadDashboard, 30000);
