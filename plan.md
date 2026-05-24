# SFPE-5M — Phase 5 Execution Plan (locked 2026-05-24)

## 1) Objectives
- Deliver Phase 5 evaluation pipeline outputs (CSV/MD/PNG) with strict causality (no lookahead) and spec ordering.
- Close the roll-detection blocker with verified before/after counts and tests.
- Produce a working backtest run (strategy + baselines) with required audits, equity curves, stress-window breakdowns, and slippage/cost sensitivities.

## 2) Implementation Steps

### Phase 1 — Core-flow POC (isolation) 
**User stories**
1. As a researcher, I can run a minimal script that loads one symbol and produces a deterministic set of roll flags (legacy vs v1.4).
2. As a researcher, I can run a minimal script that converts ensemble outputs into trades with next-bar-open fills.
3. As a researcher, I can verify same-bar stop/target ambiguity resolves conservatively (stop first).
4. As a researcher, I can verify roll-skip prevents entries immediately after flagged roll dates.
5. As a researcher, I can generate a per-instrument equity curve from the trades.

**POC steps (must pass before broader build-out)**
- P1.1 Diagnostic-only MD: write `reports/v1_4_micros_vs_majors.md` (no code changes).
- P1.2 Roll detector verification runner (script-only):
  - Add `scripts/run_roll_audit.py` to run all 9 instruments and output:
    - `reports/v1_4_roll_candidates.csv` (legacy + v1.4 outputs)
    - `reports/v1_4_roll_audit.md` (before/after counts per instrument)
  - Change roll default: `RollDetectionParams.atr_mult` **10.0 → 8.0**.
  - Ensure v1.4 uses **8×ATR + calendar + volume z-score** with `require_all_conditions=True`.
- P1.3 Minimal backtest POC (single instrument, fixed settings):
  - Add `scripts/poc_backtest_single.py` that:
    - loads one instrument
    - loads/derives signals from existing projection outputs
    - runs `EventEngine` with `fixed_tick` cost
    - saves trades CSV + one equity PNG

### Phase 2 — V1 Phase-5 app/dev wiring (repo-level)
**User stories**
1. As a researcher, I can `python scripts/run_backtest.py` and get all Phase 5 artifacts for strategy + baselines.
2. As a researcher, I can run the backtest at confidence thresholds 0.50 and 0.65 and compare results.
3. As a researcher, I can run slippage sensitivity (1×/2×/3×) across cost models and see impacts.
4. As a researcher, I can see per-instrument equity curves and confirm the portfolio isn’t carried by one symbol.
5. As a researcher, I can see stress-window performance broken out (COVID/rates/banks + open/close 30m).

**Build steps**
- P2.1 Fix package import break:
  - Implement `src/sfpe/backtest/baselines.py` (required by `__init__.py`).
  - Confirm/quote the exact spec §12 list in `BLOCKERS.md` when added (if any ambiguity, mark as interpretation).
- P2.2 Backtest correctness upgrades (engine + portfolio orchestration):
  - Create `src/sfpe/backtest/portfolio.py` to enforce **family concurrency at portfolio aggregation** (ES/MES etc.), while per-instrument runs remain independent.
  - Ensure roll-skip uses verified roll flags (from Phase 5.1 output) mapped to source-bar indices.
  - Fix stress windows in `EventEngine` to match locked dates:
    - COVID 2020-02-20..2020-05-31
    - Rate-shock 2022-06-01..2022-10-31
    - Banking stress 2023-03-01..2023-09-30
- P2.3 Reporting + drivers:
  - Add `scripts/run_backtest.py` (main Phase 5 runner):
    - per instrument: generate signals (existing ensemble: `bias`, `trade_eligible`, `ensemble_confidence`)
    - run strategy at thresholds 0.50 and 0.65
    - cost models: fixed_tick (fee-based primary), impact, roll_spread
    - slippage mult: 1×/2×/3×
    - portfolio aggregation with family constraint
  - Add report writers under `reporting/` for:
    - trade dumps CSV
    - metrics tables CSV
    - equity curve PNG per instrument + portfolio
    - stress-window breakdown columns

### Phase 3 — Testing & validation gates (pytest)
**User stories**
1. As a researcher, I can trust roll detection is causal (truncation doesn’t change earlier flags).
2. As a researcher, I can trust backtests fill on next-bar open and never read future bars.
3. As a researcher, I can trust stop/target tie-breaks are conservative.
4. As a researcher, I can trust session-end flatten always happens.
5. As a researcher, I can trust family concurrency is enforced at portfolio level.

**Test steps**
- P3.1 Add `tests/test_roll_detection.py`:
  - `test_legacy_v1_count_vs_v1_4_count` (v1.4 count < legacy count)
  - `test_no_lookahead_roll_detection` (truncate tail sessions; earlier flags unchanged)
  - `test_calendar_gate_correctness` (synthetic data: non-roll month gap must not flag)
- P3.2 Add `tests/test_backtest.py`:
  - `test_backtest_next_bar_fill` (spec §15)
  - `test_backtest_no_lookahead` (truncate tail bars; earlier trades unchanged)
  - `test_same_bar_stop_first` (spec §8.3)
  - `test_session_end_flatten`
  - `test_family_concurrency_portfolio`
  - `test_roll_skip`
- Run after each major change: `python -m pytest /app/sfpe_5m/tests -q`.

### Phase 4 — Phase 5 deliverables (evaluation, not optimization)
**User stories**
1. As a researcher, I can see roll-audit counts and decide whether to proceed.
2. As a researcher, I can see trade counts before interpreting PF/Sharpe.
3. As a researcher, I can compare strategy vs 10 baselines on identical frictions.
4. As a researcher, I can inspect stress-window performance columns.
5. As a researcher, I can compare confidence thresholds (0.50 vs 0.65) as a calibration sanity check.

**Deliverables**
- Phase 5.0: `reports/v1_4_micros_vs_majors.md` (short bullets).
- Phase 5.1 (STOP after this):
  - `reports/v1_4_roll_audit.md` + `reports/v1_4_roll_candidates.csv`
  - Update `BLOCKERS.md` §9/§28 as RESOLVED with actual counts + final params.
- Phase 5.4 Trade-count audit first:
  - `reports/v1_4_trade_count_audit.md` (per instrument + portfolio; both confidence thresholds).
  - If portfolio < 200 OR any active instrument < 50: stop and report before PF/Sharpe.
- Phase 5 summary (only after audit gate):
  - `reports/v1_4_phase5_summary.md`
  - Equity curves PNGs per instrument + portfolio
  - Baseline comparison table
  - Slippage sensitivity table (1×/2×/3×) and one run including roll-spread proxy comparison
  - Stress-window columns: COVID/rates/banks + open 30m + close 30m

## 3) Next Actions (immediate)
1. Create `reports/v1_4_micros_vs_majors.md` from existing diagnostics (no code).
2. Change `RollDetectionParams.atr_mult` to 8.0; add `scripts/run_roll_audit.py`.
3. Add roll-detection tests; run pytest.
4. Produce roll audit MD/CSV; update BLOCKERS §9/§28; **STOP and request user confirmation** to proceed.

## 4) Success Criteria
- Phase 5.0 MD delivered (concise, evidence-backed).
- Roll audit produced with per-instrument legacy vs v1.4 counts; v1.4 count materially lower; tests pass.
- Backtest module imports succeed (baselines exists), and backtest tests enforce:
  - next-bar open fill,
  - conservative stop-first,
  - session-end flatten,
  - roll-skip,
  - portfolio family concurrency.
- Trade-count audit produced before PF; if insufficient sample sizes, process pauses.
- Final Phase 5 summary includes per-instrument + portfolio curves, baseline table, slippage/cost sensitivity, and stress-window breakdowns.
