# SFPE-5M  —  Synthetic Forward-Projection Trading Engine, 5-Minute Edition

**Status:** v1 (Phases 0–2, partial).  Research-grade Python repo.  No live trading. No broker. No Pine Script in v1.

This repository implements the SFPE-5M system as specified in `SFPE_5M_Agent_Prompt_v2.md.pdf`. It develops, optimizes (in later versions), and validates a futures trading strategy that does not rely on traditional trend-following or retail indicator stacking. Instead, it constructs **synthetic market candles** from completed 5-minute OHLCV bars, with the goal of (in later versions) forward-projecting the next synthetic candle's completion under structural constraints.

## What v1 delivers (this build)

- **Phase 0** — full repo scaffold per spec §4, exact configs per spec §3 (instruments.yaml, session_calendars.yaml, portfolio.yaml).
- **Phase 1** — data audit + integrity + roll detection for all 9 instruments. Produces:
  - `reports/data_integrity_summary.md`
  - `reports/data_integrity_by_instrument.csv`
  - `reports/roll_candidates.csv`
  - `reports/session_coverage_heatmap.png`
- **Phase 2 (priority engines only)**:
  - **Engine C** (`vol_budget`): Parkinson-variance budget synthetic candles.
  - **Engine A** (`dollar_imbalance`): signed-notional imbalance synthetic candles with causal threshold bootstrap.
  - Engines **B** (`volume_time`) and **D** (`range_budget`) are stubbed with `NotImplementedError`; see v2.
- **Mandatory no-lookahead test** — every engine ships with a truncate-at-midpoint vs full-run comparison; bytes-identical historic output is required.

## What v1 explicitly defers

- Synthetic engines B and D.
- Features layer (absorption, VPIN proxy, TPO, liquidity vacuum, regime router, magnitude projection).
- Forward projection module and ensemble.
- Strategy logic, position sizing, exits.
- Event-driven backtest, baselines, slippage/cost models.
- Walk-forward optimization (when delivered, will use fast protocol: 12m train / 3m val / 3m test / 1m step).
- Final reporting + PASS/FAIL verdict.
- **Pine Script export** — per spec §18 rule #10, no Pine code is generated until a Walk-Forward PASS verdict exists.

## Quickstart

```bash
cd /app/sfpe_5m
pip install -r requirements.txt

# Place CSVs (already done for this build) at:
#   data/raw/ES_5min_RTH_6year.csv  (and the 8 other instruments)

# 1. Verify core mechanics on real ES data (must pass before anything else):
python scripts/test_core.py

# 2. Run Phase 1 data audit for all 9 instruments:
python scripts/run_data_audit.py

# 3. Run priority synthetic engines (Engine C + Engine A) for selected symbols:
python scripts/run_engines.py --symbols ES MES MNQ --engines vol_budget dollar_imbalance

# 4. Run end-to-end v1 pipeline (audit + engines for all instruments):
python scripts/run_pipeline.py

# 5. Run pytest suite (data integrity + engines + no-lookahead test):
pytest -q tests/
```

## Dataset

9 instruments, ~5 years of 5-minute RTH OHLCV bars each, schema `ts_event,symbol,open,high,low,close,volume`:

| Symbol | Family | Calendar | Notes |
|--------|--------|----------|-------|
| ES     | sp500    | RTH_eq    | E-mini S&P 500 |
| MES    | sp500    | RTH_eq    | Micro E-mini S&P 500 |
| MNQ    | nasdaq   | RTH_eq    | Micro E-mini Nasdaq-100 |
| YM     | dow      | RTH_eq    | E-mini Dow |
| MYM    | dow      | RTH_eq    | Micro E-mini Dow |
| RTY    | russell  | RTH_eq    | E-mini Russell 2000 |
| M2K    | russell  | RTH_eq    | Micro Russell 2000 |
| MGC    | gold     | RTH_comex | Micro Gold (some bars start at 08:20 ET — see BLOCKERS.md) |
| MCL    | oil      | RTH_nymex | Micro Crude (dataset starts 2021-07-12) |

## Anti-overfitting and causality guarantees

- All rolling/EMA computations use `shift(1)` or session-aware accumulators that touch only past data.
- `tests/test_no_lookahead.py` runs each engine on `df.iloc[:k]` and on full `df`, and asserts that every synthetic bar with `end_idx < k` is byte-identical between the two runs.
- Configurations are reproducible from the YAML in `config/`.
- No Pine code is generated. No broker integration exists.

## Documented defaults

See `BLOCKERS.md` for every decision made when the spec was ambiguous, the default chosen, and the rationale.
