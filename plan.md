# SFPE-5M — Phase 5 Execution Plan (locked 2026-05-24) — **UPDATED (Phase 5 COMPLETE)**

## 1) Objectives
- **(Achieved)** Deliver Phase 5 evaluation pipeline outputs (CSV/MD/PNG) with strict causality (no lookahead) and spec ordering.
- **(Achieved)** Close the roll-detection blocker with verified before/after counts and tests (legacy 4,551 → v1.4 498; user-approved Option A).
- **(Achieved)** Produce a working backtest run (strategy + baselines) with required audits, equity curves, stress-window breakdowns, and slippage/cost sensitivities.
- **(Achieved; negative result)** Produce an **honest Phase 5 verdict** without optimization: strategy FAILS realized P&L across all tested variants; calibration from Phase 4 does not translate to P&L.
- **(New objective post-Phase-5)** Prepare for owner decision on next steps (Phase 6 walk-forward vs stop vs diagnostics). **No work starts on Phase 6 until explicitly authorized.**

## 2) Implementation Steps

### Phase 1 — Core-flow POC (isolation)
**User stories**
1. As a researcher, I can run a minimal script that loads one symbol and produces a deterministic set of roll flags (legacy vs v1.4).
2. As a researcher, I can run a minimal script that converts ensemble outputs into trades with next-bar-open fills.
3. As a researcher, I can verify same-bar stop/target ambiguity resolves conservatively (stop first).
4. As a researcher, I can verify roll-skip prevents entries immediately after flagged roll dates.
5. As a researcher, I can generate a per-instrument equity curve from the trades.

**POC steps (must pass before broader build-out)**
- ✅ P1.1 Diagnostic-only MD: wrote `reports/v1_4_micros_vs_majors.md`.
  - Key correction captured: **YM and MYM both fail** Phase 4 close-in-zone gate; only ES/MES and RTY/M2K show micro-vs-major divergence.
- ✅ P1.2 Roll detector verification runner:
  - Implemented `scripts/run_roll_audit.py` and produced:
    - `reports/v1_4_roll_candidates.csv` (legacy + v1.4 outputs)
    - `reports/v1_4_roll_audit.md` (before/after counts per instrument)
  - Updated default `RollDetectionParams.atr_mult` **10.0 → 8.0**.
  - v1.4 uses **8×ATR + calendar + volume z-score**, `require_all_conditions=True`.
  - Results: legacy=4,551 → v1.4=498 (89.1% drop). Commodities elevated due to inherent monthly/bi-monthly cadence; **Option A accepted by owner**.
- ✅ P1.3 Minimal backtest POC became unnecessary because full backtest runner was implemented and validated; smoke-tested with single symbol runs via `scripts/run_backtest.py --symbols ES`.

### Phase 2 — V1 Phase-5 app/dev wiring (repo-level)
**User stories**
1. As a researcher, I can `python scripts/run_backtest.py` and get all Phase 5 artifacts for strategy + baselines.
2. As a researcher, I can run the backtest at confidence thresholds 0.50 and 0.65 and compare results.
3. As a researcher, I can run slippage sensitivity (1×/2×/3×) and compare cost models.
4. As a researcher, I can see per-instrument equity curves and confirm the portfolio isn’t carried by one symbol.
5. As a researcher, I can see stress-window performance broken out (COVID/rates/banks + open/close 30m).

**Build steps**
- ✅ P2.1 Fix package import break + baselines:
  - Implemented `src/sfpe/backtest/baselines.py` with **10 baselines**.
  - Documented spec §12 baseline list as **interpretation** in `BLOCKERS.md §40`.
- ✅ P2.2 Backtest correctness upgrades (engine + portfolio orchestration):
  - Implemented `src/sfpe/backtest/portfolio.py` enforcing **family concurrency at portfolio level**.
  - Implemented roll-skip mapping in `src/sfpe/backtest/runner.py` using `reports/v1_4_roll_candidates.csv`.
  - Updated stress windows in backtest engine:
    - COVID 2020-02-20..2020-05-31
    - Rate-shock 2022-06-01..2022-10-31
    - Banking stress 2023-03-01..2023-09-30 (user lock; BLOCKERS §39)
- ✅ P2.3 Reporting + drivers:
  - Implemented `src/sfpe/backtest/signals.py` to **recompute trade_eligibility** (fixes cached CSV UTC/ET bug; BLOCKERS §38).
  - Implemented `src/sfpe/backtest/runner.py` orchestrator: 9 instruments × 10 strategy variants + 10 baselines.
  - Implemented `scripts/run_backtest.py` (Phase 5 master runner) writing all mandatory artifacts.
  - Performance fix: removed per-trade allocation of `pd.Series([0]*n)` inside cost calls by precomputing arrays in `EventEngine` (10×+ speedup).

### Phase 3 — Testing & validation gates (pytest)
**User stories**
1. As a researcher, I can trust roll detection is causal (truncation doesn’t change earlier flags).
2. As a researcher, I can trust backtests fill on next-bar open and never read future bars.
3. As a researcher, I can trust stop/target tie-breaks are conservative.
4. As a researcher, I can trust session-end flatten always happens.
5. As a researcher, I can trust family concurrency is enforced at portfolio level.

**Test steps**
- ✅ P3.1 Roll detection tests: `tests/test_roll_detection.py` (7 tests)
  - legacy ≥ v1.4 count
  - no-lookahead truncation invariance
  - calendar gate blocks non-roll months
  - calendar gate allows roll months
  - requires all 3 conditions
  - monthly oil family behavior
- ✅ P3.2 Backtest tests: `tests/test_backtest.py` (21 tests)
  - spec §15 next-bar fill
  - no-lookahead truncation invariance
  - spec §8.3 conservative stop-first on same bar
  - session-end flatten
  - roll-skip
  - portfolio family concurrency
  - baseline causality
  - signal recompute alignment checks
- ✅ Full suite: `python -m pytest tests/` → **70 passed / 0 failed**.

### Phase 4 — Phase 5 deliverables (evaluation, not optimization)
**User stories**
1. As a researcher, I can see roll-audit counts and decide whether to proceed.
2. As a researcher, I can see trade counts before interpreting PF/Sharpe.
3. As a researcher, I can compare strategy vs 10 baselines on identical frictions.
4. As a researcher, I can inspect stress-window performance columns.
5. As a researcher, I can compare confidence thresholds (0.50 vs 0.65) as a calibration sanity check.

**Deliverables**
- ✅ Phase 5.0:
  - `reports/v1_4_micros_vs_majors.md`
- ✅ Phase 5.1:
  - `reports/v1_4_roll_audit.md`
  - `reports/v1_4_roll_candidates.csv`
  - `BLOCKERS.md §9/§28` updated as RESOLVED (user-approved Option A).
- ✅ Phase 5.4 Trade-count audit FIRST:
  - `reports/v1_4_trade_count_audit.md`
  - `reports/v1_4_phase5_trade_count_audit.csv`
  - Gate: ✅ PASS (portfolio ≥200 trades AND each active instrument ≥50)
- ✅ Phase 5 Summary + artifacts:
  - `reports/v1_4_phase5_summary.md`
  - `reports/v1_4_phase5_metrics.csv`
  - `reports/v1_4_phase5_baselines.csv`
  - `reports/v1_4_phase5_slippage_table.csv`
  - `reports/v1_4_phase5_stress_windows.csv`
  - `reports/v1_4_phase5_roll_skip_blocked.csv` (includes owner’s “>5% blocked” flags: commodities only)
  - Per-instrument equity curves: `reports/v1_4_phase5_per_instrument_equity__<SYM>.csv/.png`
  - Portfolio equity curves: `reports/v1_4_phase5_portfolio_equity__conf=0.50.csv/.png`, `...conf=0.65...`
- ✅ Consolidated honest verdict:
  - `reports/v1_4_phase5_VERDICT.md`

**Phase 5 verdict (honest; no tuning applied)**
- Strategy FAILS realized P&L across every instrument and variant.
- Portfolio (family-concurrency enforced, 1× slippage, fixed_tick): PF ≈ 0.79–0.80; net P&L roughly −$228k to −$279k on $100k starting equity.
- Calibration sanity check FAILS: conf 0.50 vs 0.65 yields essentially unchanged PF/win-rate.
- Slippage sensitivity suggests gross edge < 1 tick.
- COVID window: 0 trades (regime filter kept flat).

## 3) Next Actions (immediate)
**Phase 5 is complete; next actions are decision-only. No Phase 6 work begins until explicitly authorized.**
1. Owner chooses one option:
   - **A)** Accept negative verdict and stop.
   - **B)** Authorize **Phase 6 walk-forward optimization** (spec §13) with strict out-of-sample validation.
   - **C)** Request a diagnostic deep-dive (why stop/target overlay destroys edge; trade distribution analysis).
   - **D)** Request a research variant removing/relaxing the regime filter (currently blocks most bars).
2. If Phase 6 is authorized, create a new Phase 6 plan with explicit guardrails:
   - walk-forward splits
   - parameter search space
   - evaluation metric definitions
   - overfitting controls (PBO/DSR)

## 4) Success Criteria
- ✅ Phase 5.0 diagnostic MD delivered (concise, evidence-backed).
- ✅ Roll audit produced with per-instrument legacy vs v1.4 counts; v1.4 materially lower; tests pass.
- ✅ Backtest module imports succeed; tests enforce:
  - next-bar open fill,
  - conservative stop-first,
  - session-end flatten,
  - roll-skip,
  - portfolio family concurrency.
- ✅ Trade-count audit produced **before** PF/Sharpe; audit gate passed.
- ✅ Final Phase 5 outputs include per-instrument + portfolio curves, baseline table, slippage/cost sensitivity, stress-window breakdown, and roll-skip blocked log.
- ✅ Full pytest suite passes: **70 tests**.
- ✅ Final Phase 5 verdict documented honestly in `reports/v1_4_phase5_VERDICT.md`.
