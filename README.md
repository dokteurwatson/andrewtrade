# AndrewTrade Paper Trader

`andrewtrade` is a Dockerized paper trading bot that uses Kraken market data on a `4h` strategy and sends Telegram updates for startup, entries, exits, runtime errors, and a Bugatti-progress message after each profitable sell.

## Features

- Strategy rules:
  - Entry: `Close > SMA(200)` and `RSI(2) < 20`
  - Exit: `RSI(2) > 70` or stop-loss (above threshold mode)
- Coin universe via env array (`COIN_LIST`) with default `BTC,ETH,XRP`
- Balance-threshold risk switch:
  - Below threshold: all-in mode
  - At/above threshold: risk-based sizing + hard limits
- Telegram notifications:
  - startup
  - entry
  - exit
  - runtime error
  - Bugatti progress on profitable exits
- State persistence in `./state`
- Built-in dashboard with:
  - cash display
  - ongoing and completed trades
  - dynamic trade potential scoring
  - candle chart with projected strategy entry/exit markers

## Project Layout

- App package: `papertrader/`
- Tests: `tests/`
- Runtime state: `state/`
- Config template: `.env.example`

## Requirements

- Docker + Docker Compose
- Telegram bot token + chat id for alerts

## Quick Start

1. Copy env template:

```bash
cp .env.example .env
```

2. Fill Telegram credentials in `.env`:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

3. Optional watchlist override with DOGE:

```env
COIN_LIST=["BTC","ETH","XRP","DOGE"]
```

4. Start:

```bash
docker compose up --build -d
```

If you hit an image-name conflict while building both services, run:

```bash
docker compose build andrewtrade-api
docker compose up -d
```

The dashboard service reuses the same built image and does not trigger a second build.

5. Follow logs:

```bash
docker compose logs -f papertrader
```

API logs:

```bash
docker compose logs -f andrewtrade-api
```

Dashboard logs:

```bash
docker compose logs -f andrewtrade-dash
```

6. Stop:

```bash
docker compose down
```

Dashboard (when running locally):

- `http://localhost:8000`

## Environment Variables

Core:

- `MODE=paper`
- `EXCHANGE_ID=kraken`
- `TIMEFRAME=4h`
- `COIN_LIST=["BTC","ETH","XRP"]`
- `PAPER_START_CAPITAL_USD=50`

Risk model:

- `RISK_THRESHOLD_BALANCE=100`
- `POSITION_SIZING_BELOW_THRESHOLD=all_in`
- `RISK_PER_TRADE_ABOVE_THRESHOLD=0.01`
- `STOP_LOSS_PCT_ABOVE_THRESHOLD=0.02`
- `MAX_DAILY_LOSS_ABOVE_THRESHOLD=0.03`
- `MAX_OPEN_POSITIONS_ABOVE_THRESHOLD=1`
- `MAX_CONSECUTIVE_LOSSES_ABOVE_THRESHOLD=3`
- `COOLDOWN_CANDLES_AFTER_LIMIT=3`

Costs:

- `TAKER_FEE_RATE=0.0026`
- `SLIPPAGE_RATE=0.0005`

Runtime:

- `POLL_SECONDS=60`
- `CANDLE_LIMIT=300`
- `MIN_ORDER_USD=10`
- `STATE_DIR=./state`
- `LOG_LEVEL=INFO` (`DEBUG`, `WARNING`, `ERROR` also supported)

Telegram:

- `TELEGRAM_ENABLED=true`
- `TELEGRAM_BOT_TOKEN=...`
- `TELEGRAM_CHAT_ID=...`

Bugatti tracker:

- `BUGATTI_TARGET_USD=2000000` (defaults to entry-level Bugatti territory)

## Telegram Messages You Get

- Startup message with exchange/timeframe/coins/cash/mode
- Entry message with symbol, size, indicators, fee
- Exit message with reason, PnL, fee
- Runtime error message if a cycle fails
- Extra message after profitable exit with:
  - target progress percentage
  - a fun status line based on percentage range

## Docker Registry

Compose is set up with image:

- `registry.dizzyman.nl/andrewtrade:latest`

Build and push manually:

```bash
docker build -t registry.dizzyman.nl/andrewtrade:latest .
docker push registry.dizzyman.nl/andrewtrade:latest
```

## Kubernetes / Helm Deployment

Use these defaults for cluster deploys.

### Required persistence path

- Mount persistent storage at: `/app/state`
- Set env var: `STATE_DIR=/app/state`

This persists:

- `/app/state/paper_state.json` (cash, positions, cooldown/day state)
- `/app/state/trades.jsonl` (trade event log)

### Required secrets/config

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- Optional: move all env config into a ConfigMap + Secret split

### Minimal Helm values example

```yaml
image:
  repository: registry.dizzyman.nl/andrewtrade
  tag: latest
  pullPolicy: IfNotPresent

env:
  MODE: "paper"
  EXCHANGE_ID: "kraken"
  TIMEFRAME: "4h"
  COIN_LIST: '["BTC","ETH","XRP"]'
  PAPER_START_CAPITAL_USD: "50"
  STATE_DIR: "/app/state"
  LOG_LEVEL: "INFO"
  TELEGRAM_ENABLED: "true"

secretEnv:
  TELEGRAM_BOT_TOKEN: "<set-in-secret>"
  TELEGRAM_CHAT_ID: "<set-in-secret>"

persistence:
  enabled: true
  size: 1Gi
  accessMode: ReadWriteOnce
  mountPath: /app/state
```

### Deployment notes

- Run a single replica (`replicaCount: 1`) to avoid multiple bots trading the same paper wallet.
- Keep rolling updates simple (`maxUnavailable: 0`, `maxSurge: 1`) so only one active pod remains.
- If your registry is private, configure `imagePullSecrets` in the chart.
- Add resource requests/limits so pod eviction risk is lower on busy clusters.

### Example upgrade command

```bash
helm upgrade --install andrewtrade ./chart \
  --set image.repository=registry.dizzyman.nl/andrewtrade \
  --set image.tag=latest
```

## Testing

Run tests locally:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
pytest -q
```

Current suite covers config parsing, indicators, and key runner risk flows.

## Trade Frequency Estimation

To estimate expected entry/exit count per month with your current strategy settings:

```bash
python -m papertrader.backtest_frequency
```

This pulls recent OHLC candles from Kraken using your `.env` config (`COIN_LIST`, `TIMEFRAME`, `CANDLE_LIMIT`, RSI/SMA thresholds) and prints:

- entries per symbol
- exits per symbol
- approximate months covered
- entries per month per symbol
- portfolio aggregate entries/month

## Notes

- This bot is paper-only right now (`MODE=paper`).
- No live Kraken order placement is implemented yet.

## Dashboard Server

Run the dashboard API + frontend:

```bash
uvicorn papertrader.dashboard:app --host 0.0.0.0 --port 8000
```

Endpoints:

- `GET /api/dashboard` -> wallet/trades/potential summary
- `GET /api/chart?symbol=BTC/USD&limit=350` -> candles + SMA + projected ENTRY/EXIT markers
