# SFPE-5M  —  Synthetic Forward-Projection Trading Engine, 5-Minute Edition

**Status: v1.5 — FINAL.  Research-grade NEGATIVE result.  No tradeable edge found.  No live trading. No broker. No Pine Script.**

---

## PROJECT VERDICT (2026-05-24)

**SFPE-5M was a research-grade NEGATIVE result on 6 years of 5-minute RTH futures across 9 instruments** (ES, MES, MNQ, YM, MYM, RTY, M2K, MGC, MCL).

The synthetic-projection concept produces **directionally informative** output: price visits *some* part of the projected close envelope `[projected_close_low, projected_close_high]` on **98.8 %** of trades within 3× the forecast horizon. But the projection envelope is a **landing-zone forecast, not a journey forecast**. Only **24.2 %** of trades traverse the full zone width to reach TP2 (`projected_close_high` for long / `projected_close_low` for short). The remaining 76 % wiggle into the zone, then leave, then sometimes return — but the spec §8.3 trade-management overlay (structural stop ± 0.5 × ATR; time-stop = ceil(projected_completion_median × 1.5); TP1 partial; TP2 runner) is **economically incompatible with that landing-zone geometry**.

### Decision-tree triggers (set in advance, locked by owner before forensic analysis ran)

| Metric | Threshold | Observed | Triggered |
|---|---|---|---|
| Wider-stop only (W1) → TP2 conversion | ≥ 40 % → Phase 6 justified ; < 20 % → wider stops won't save it | **1.7 %** | <20 % stop signal |
| Wider-stop + longer-hold (W2) → TP2 conversion | 40–60 % band → "tunable but marginal" | **7.0 %** | below the band |
| Projection durability (TP2 within 3× horizon) | < 30 % → A_STOP | **24.2 %** | **A_STOP** |

All three criteria triggered the same verdict: **A_STOP — accept the negative result, do not run Phase 6.**

### Bottom-line strategy economics (conf=0.65, fixed_tick, 1× slippage)

- Portfolio over 5 years on $100,000 starting equity: **PF = 0.77, net P&L = −$146,257, Sharpe = −1.63.**
- 4,110 trades.  Exit reasons: **49 % stop / 43 % time-stop / 6 % TP2 / 2 % session-end.**
- TP2 wins average +$361 (R:R ≈ 1.3 vs stop). The strategy can win — it just doesn't win often enough.
- The strategy is **statistically indistinguishable from the 10 baselines** in PF (mean 0.74–0.80) and is the **worst in Sharpe** (more concentrated losing exposure per trade).

**No tradeable edge was found. No Pine Script will be generated** (spec §18 rule #10: Pine is only authorised after a Walk-Forward PASS verdict, which never occurred).

---

## Key research findings

### 1. The landing-zone vs journey distinction
The Phase 4 §11.2 close-in-zone gate measures whether the **session-close price** lands within the projected envelope. It does NOT measure whether the in-bar **journey** to that close traverses the upper or lower envelope.
On a 5-minute timeframe, intra-session price action wiggles in and out of the projected zone freely (98.8 % zone-visit rate) but only **24 %** of trades actually push to the far envelope edge before mean-reverting. The §11.2 gate was ~70 % accurate for what it claimed to forecast — **but what it claims to forecast is not actionable under a stop / target trade-management overlay.**

### 2. The wider-grid hypothesis is REFUTED
Earlier intuition suggested that families with **wider round-number grids** (Dow at 100 pts, Gold at $10) might accommodate the projection envelope better than tighter grids (S&P at 5 pts). Forensic analysis on `grid_points / median_ATR` ratio vs TP2 win rate shows **no relationship**: MES (ratio 0.86) and YM (ratio 2.61) both have ~9 % TP2 win rates; MNQ (0.98) and MYM (2.52) both have ~5 %. The wider-grid effect on YM/MNQ that appeared in v1.5 (PF 0.94 / 0.90) was sample-level noise, not a structural advantage.

### 3. Marginal signal candidates (still unprofitable)
Two sub-populations showed elevated TP2 hit-rates vs the 6.4 % overall baseline:

| Sub-population | TP2 win rate | n_trades |
|---|---|---|
| Closing-30-min entries (15:00–15:30 ET) | 10.2 % | 660 |
| Trades with `failed_auction` override in `reason_codes` | 8.4 % | 1,484 |
| Closing-30-min × failed_auction (intersection) | ~10 % | ~200 |

These are statistically meaningful effects (~50 % uplift over baseline) but at ~10 % TP2 hit rate the strategy is still firmly unprofitable under spec §8.3 economics. Documented for future research; not exploited.

### 4. Test discipline
The full pytest suite — **90/90 PASS** — was maintained throughout every phase, including:
- `tests/test_no_lookahead_*.py` — truncate-at-midpoint causal invariance.
- `tests/test_synthetic_engines.py` — engine acceptance gates per spec §11.1.
- `tests/test_features.py` — feature layer + no-lookahead.
- `tests/test_projection.py` — ensemble math + geometric-mean confidence (BLOCKERS §29).
- `tests/test_roll_detection.py` — v1.4 detector (8× ATR + calendar + volume).
- `tests/test_backtest.py` — next-bar fill, conservative stop-first, session-end, family concurrency, baseline causality.
- `tests/test_projection_exits.py` — spec §8.3 projection-aware exits (TP1/TP2, structural anchor, fallback, time-stop, partial leg).
- `tests/test_data_integrity.py` — schema + dataset audit.

No claimed result rests on un-tested code.

---

## What's reusable (the toolkit, even though the strategy isn't)

These components are **strategy-agnostic** and transfer cleanly to future hypotheses:

| Component | Module | What it does |
|---|---|---|
| Causal data loader | `src/sfpe/data/loader.py` | tz-aware (`America/New_York`), session-bounded, ATR_20 pre-computed |
| Roll detection v1.4 | `src/sfpe/data/roll_detection.py` | 8× ATR + calendar gating + volume z-score, 89 % drop over the legacy 5× ATR |
| Session integrity auditor | `src/sfpe/data/integrity.py` | PASS/WARN/FAIL audit per instrument |
| Synthetic-bar engines (4) | `src/sfpe/synthetic/` | vol_budget (variance-proxy), dollar_imbalance, volume_time, range_budget — all causal, all unit-tested |
| Structural feature layer (6) | `src/sfpe/features/` | absorption, VPIN proxy, TPO, liquidity vacuum, regime router, magnitude projection |
| Forward-projection ensemble | `src/sfpe/projection/` | per-engine projection + ensemble math + geometric-mean confidence |
| Event-driven backtest engine | `src/sfpe/backtest/event_engine.py` | next-bar fills, conservative same-bar stop-first, session-end flatten, projection-aware exits (TP1/TP2/structural stop/time-stop) OR legacy ATR exits |
| Cost models (3) | `src/sfpe/backtest/cost_models.py` | fixed_tick (realistic CME fees + 1 tick slip), roll_spread (microstructure-aware), impact (price-impact) |
| Mandatory baselines (10) | `src/sfpe/backtest/baselines.py` | buy_and_hold_intraday, prior_bar_momentum, prior_bar_mean_reversion, atr_breakout, vwap_mean_reversion, opening_range_breakout, random_entry_matched_holding, ema_crossover_9_21, donchian_channel_20, bollinger_mean_reversion_20 — all causal, parametrized causality-test included |
| Portfolio orchestrator | `src/sfpe/backtest/portfolio.py` | family concurrency limit (one position per family across micros + majors) |
| Forensic post-mortem | `scripts/run_phase5_postmortem.py` | counterfactual replay engine for stopped trades + projection durability checker |
| Walk-forward harness | unused but functional | spec §13 protocol (12-month train / 3-month val / 3-month test / 1-month step) — never invoked because no Phase 5 PASS was achieved |

All components are decoupled and individually importable.

---

## Phase status (final)

| Phase | Status | Deliverable |
|---|---|---|
| 0. Scaffold | DONE | `BLOCKERS.md`, configs, project structure |
| 1. Data audit + roll detection | DONE | `reports/data_integrity_*`, `reports/v1_4_roll_audit.md` |
| 2. Synthetic engines (4) | DONE | acceptance gates met per spec §11.1, all engines causal |
| 3. Feature layer (6) | DONE | 6 features × 9 instruments, all causal |
| 4. Forward projection ensemble | DONE | session-close envelope, geometric-mean confidence, §11.2 gate ~70 % hit-rate |
| 5. Event-driven backtest | DONE | spec §9 + §8.3 projection-aware exits, 10 baselines, 3 cost models, 3 slippage, family concurrency |
| 5.5 Forensic post-mortem | DONE | `reports/v1_5_phase5_postmortem.md` — **A_STOP verdict** |
| 6. Walk-forward optimization | **NOT EXECUTED** — Phase-5 PASS gate not achieved, optimization is not authorised |
| 7. Pine Script export | **NEVER EXECUTED** — spec §18 rule #10 blocks Pine until Walk-Forward PASS |

---

## Final deliverables (all in `reports/`)

- **`v1_5_phase5_VERDICT.md`** — primary Phase-5 verdict (projection-aware exits).
- **`v1_5_phase5_postmortem.md`** — Option C forensic post-mortem with decision-tree verdict.
- **`v1_5_phase5_postmortem_trades.csv`** — 4,741-row per-trade ledger with W1/W2/durability counterfactual fields.
- **`v1_5_phase5_postmortem_winners.csv`** — TP2-winner feature profile.
- `v1_4_phase5_summary.md`, `v1_4_phase5_metrics.csv` — detailed Phase 5 tables.
- `v1_4_phase5_baselines.csv`, `v1_4_phase5_slippage_table.csv`, `v1_4_phase5_stress_windows.csv`, `v1_4_phase5_roll_skip_blocked.csv`.
- Per-instrument equity curves: `v1_4_phase5_per_instrument_equity__<SYM>.csv` + `.png`.
- Portfolio equity curves: `v1_4_phase5_portfolio_equity__conf=0.50.csv|png`, `v1_4_phase5_portfolio_equity__conf=0.65.csv|png`.
- `v1_4_roll_audit.md` + `v1_4_roll_candidates.csv` — Phase 5 Step 1 roll-detection upgrade.
- `v1_4_micros_vs_majors.md` — Phase 5.0 ES/MES + RTY/M2K projection divergence diagnostic.
- `v1_3_summary.md`, `v1_2_summary.md`, `v1_1_summary.md`, `v1_summary.md` — phase-by-phase progress notes.

**BLOCKERS.md** is the cumulative deviation / decision log (43 numbered entries). See **§43** for the final A_STOP verdict rationale.

---

## Anti-overfitting and causality guarantees (still hold)

- All rolling/EMA computations use `shift(1)` or session-aware accumulators that touch only past data.
- `tests/test_no_lookahead*.py` and `tests/test_backtest.py::test_backtest_no_lookahead_truncation_invariance` run each module on `df.iloc[:k]` and on full `df`, and assert that every output indexed `< k` is bit-identical between the two runs.
- Configurations are reproducible from YAML in `config/`.
- No live broker integration. No paper trading. No order routing. No webhook. No Pine code.
- All cost models, slippage assumptions, and stress-window dates are owner-locked in `BLOCKERS.md`.

---

## Dataset

9 instruments, ~5–6 years of 5-minute RTH OHLCV bars each, schema `ts_event,symbol,open,high,low,close,volume`:

| Symbol | Family | Calendar | Notes |
|--------|--------|----------|-------|
| ES     | sp500    | RTH_eq    | E-mini S&P 500 |
| MES    | sp500    | RTH_eq    | Micro E-mini S&P 500 |
| MNQ    | nasdaq   | RTH_eq    | Micro E-mini Nasdaq-100 |
| YM     | dow      | RTH_eq    | E-mini Dow |
| MYM    | dow      | RTH_eq    | Micro E-mini Dow |
| RTY    | russell  | RTH_eq    | E-mini Russell 2000 |
| M2K    | russell  | RTH_eq    | Micro Russell 2000 |
| MGC    | gold     | RTH_comex | Micro Gold (some bars start at 08:20 ET — see BLOCKERS §17) |
| MCL    | oil      | RTH_nymex | Micro Crude (dataset starts 2021-07-12) |

---

## Quickstart (for reproduction)

```bash
cd /app/sfpe_5m
pip install -r requirements.txt

# 0. Sanity check — pytest must pass 90/90.
pytest -q tests/

# 1. Phase 1 data audit (refreshes integrity + roll candidates).
python scripts/run_data_audit.py

# 2. Phase 1.5 roll detection v1.4 (8× ATR + calendar + vol-z).
python scripts/run_roll_audit.py

# 3. Phase 2-3-4 synthetic engines + features + projection.
python scripts/run_pipeline.py

# 4. Phase 5 backtest (10 strategy variants + 10 baselines × 9 instruments).
python scripts/run_backtest.py

# 5. Phase 5.5 Option C forensic post-mortem (no new backtest — reuses signals).
python scripts/run_phase5_postmortem.py
```

Total wall-clock for a fresh end-to-end build: ~45 min on a single Python process.

---

## Closing note

This project is closed at v1.5 (A_STOP).  Phase 6 walk-forward is **not** authorised. Pine Script generation is **not** authorised. The repository is preserved as a reproducible record of a well-tested negative result and as a reusable toolkit for the next research hypothesis.
