# Trading Strategy - Based on `masteralgoinlessthan90min`

## Goal
Create a robust, rules-based strategy from the video transcript that can be paper traded first and later automated.

## Core Strategy (Primary Candidate)

### Name
`ES_MeanReversion_RSI2_SMA200_LongOnly`

### Market + Timeframe
- Instrument: `ES` (S&P 500 futures) in the original video
- Timeframe: `1D`
- Direction: `Long only`

### Entry Rules (all must be true)
1. `Close > SMA(200)` (market regime filter)
2. `RSI(2) < 20` (short-term oversold trigger)

### Exit Rules
- Exit when `RSI(2) > 70`

### Position Sizing (video-aligned)
- Base mode: fixed size (`1 contract` for futures)
- For bot implementation: use risk-based sizing equivalent to fixed size in backtest, then scale by portfolio drawdown tolerance.

### Risk Controls
- Keep strategy-level max drawdown budget per instrument.
- If live drawdown approaches Monte Carlo worst-case drawdown threshold, reduce size or disable strategy.
- Do not increase size during drawdown recovery.

## Secondary Strategy (Optional Candidate from video)

### Name
`GoldRush_Thursday_RSI_ATR`

### Market + Timeframe
- Instrument: `GC` (Gold futures) in transcript
- Timeframe: `1D`
- Direction: `Long only`

### Entry Rules
1. `DayOfWeek == Thursday`
2. `RSI(period) < 40` (period as tested in build flow)

### Exit Rules
1. Stop loss: `1 x ATR` (volatility-based)
2. Time stop: exit after `3 bars`

### Position Sizing
- Fixed size (`1 contract`) in baseline tests

## Robustness Framework (Mandatory before live deployment)

### 1) In-sample vs Out-of-sample split
- Build on in-sample period only.
- Validate on unseen out-of-sample period.
- Reject strategy if OOS metrics degrade materially vs IS.

### 2) Parameter stability map
- Test parameter neighborhoods, not one optimized point.
- Example for RSI entry threshold: test around baseline (e.g., 10/15/20/25/30).
- Keep only strategies profitable across a wide range.

### 3) Multi-market / multi-timeframe retest
- Retest on related markets and alternative timeframes.
- Keep only strategies with acceptable behavior outside original training context.

### 4) Monte Carlo reshuffle
- Reshuffle trade sequence to estimate worst realistic path.
- Use Monte Carlo drawdown, not backtest drawdown, for sizing decisions.

### 5) Stress and data perturbation tests
- Slightly perturb OHLC or execution assumptions.
- Reject fragile strategies that collapse under small changes.

## Portfolio Management Rules (from transcript process)
- Maintain an incubation bank of paper/sim strategies.
- Promote to live only strategies that pass full robustness workflow.
- Do not disable immediately after short losing streak; compare against expected worst-case behavior first.
- If underperformance persists near expected max DD window, reduce size or rotate strategy out.
- Keep replacements ready from incubation pipeline.

## Live Governance Rules
- Track per-strategy metrics weekly: net PnL, drawdown, PF, win rate, exposure, avg trade.
- Track portfolio metrics daily: total DD, correlation clusters, capital-at-risk.
- Any strategy breaching risk policy enters `simulation-only` mode until revalidated.

## Bot-Ready Rule Spec (for implementation)

```yaml
strategy_id: ES_MeanReversion_RSI2_SMA200_LongOnly
market: ES
timeframe: 1d
side: long
entry:
  - indicator: sma
    length: 200
    condition: close_above
  - indicator: rsi
    length: 2
    condition: below
    value: 20
exit:
  - indicator: rsi
    length: 2
    condition: above
    value: 70
risk:
  sizing_mode: fixed
  fixed_units: 1
  max_strategy_drawdown_pct: 25
  use_monte_carlo_drawdown_for_sizing: true
validation:
  require_out_of_sample: true
  require_parameter_stability: true
  require_monte_carlo: true
  require_stress_tests: true
deployment:
  mode: paper_first
  promote_to_live_after_days: 30
```

## Notes for Crypto Adaptation (future Kraken use)
- Keep same logic but swap `ES` for selected crypto pairs (e.g., `BTC/USD`, `ETH/USD`).
- Recalibrate thresholds and hold times for 24/7 market behavior.
- Preserve robustness workflow unchanged before enabling real-money execution.

## Coin Universe Configuration

Use an environment variable array so coin selection is configurable without code changes.

Default (as requested):

```env
COIN_LIST=["BTC","ETH","XRP"]
```

Current watchlist (including DOGE) can be enabled by override:

```env
COIN_LIST=["BTC","ETH","XRP","DOGE"]
```

Pair mapping for Kraken-style symbols should resolve to:
- `BTC` -> `BTC/USD`
- `ETH` -> `ETH/USD`
- `XRP` -> `XRP/USD`
- `DOGE` -> `DOGE/USD`

## Balance-Based Risk Policy

Requested behavior:
- If wallet balance is below `100`, use `all-in` position sizing.
- Once wallet balance is `>= 100`, switch to normal risk controls.

Suggested environment settings:

```env
RISK_THRESHOLD_BALANCE=100
POSITION_SIZING_BELOW_THRESHOLD=all_in
RISK_PER_TRADE_ABOVE_THRESHOLD=0.01
MAX_DAILY_LOSS_ABOVE_THRESHOLD=0.03
MAX_OPEN_POSITIONS_ABOVE_THRESHOLD=1
```

Implementation logic:
1. Read current paper wallet balance.
2. If balance `< RISK_THRESHOLD_BALANCE`, position size = full available wallet for the selected pair.
3. If balance `>= RISK_THRESHOLD_BALANCE`, enforce percentage risk model and hard limits.
