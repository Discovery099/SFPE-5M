# plan.md — SFPE-5M (Pure Python) Comprehensive Plan

## 1) Objectives
- Build **SFPE-5M** as a **research-grade, pure-Python CLI repo** that operates strictly on completed **5-minute OHLCV** bars.
- Enforce **strict causality** (no lookahead) via architecture + mandatory tests.
- Deliver **v1 = Phase 0–2**: repo scaffold, data audit/integrity + roll detection, and **two priority synthetic engines** (C: Vol-budget, A: Dollar-imbalance). Engines B/D stubbed.
- Produce **clear PASS/FAIL** artifacts and diagnostics so later phases (features → projection → backtest → walk-forward → reporting) can be built safely.
- **Defer Pine export** entirely until a future version with walk-forward PASS.

## 2) Implementation Steps (phased)

### Phase 1 — Core POC (isolation; must be green before proceeding)
**Goal:** prove the hardest/riskiest core loop works on real ES data.

**User stories**
1. As a researcher, I can run `python scripts/test_core.py` and get **OK** for loader, integrity, roll detection, and 2 engines.
2. As a researcher, every failure shows the exact metric/threshold and the offending value.
3. As a researcher, truncation tests prove outputs are identical up to time *t* (no lookahead).
4. As a researcher, synthetic bars never span session boundaries.
5. As a researcher, engine quality gates report human-readable diagnostics.

**Steps**
- Websearch (brief) for best practices on: **causal rolling/EMA**, **session-boundary handling**, and **Parkinson variance** implementation details.
- Implement `scripts/test_core.py` to run on **ES** from `data/raw/`:
  - Loader derivations per spec §5.1 (timezone, session fields, returns, TR, ATR(20) causal, zscores).
  - Integrity checks per spec §5.2.
  - Roll detection per spec §5.3.
  - Engine C (Vol-budget) + Engine A (Dollar-imbalance) minimal implementations.
  - **No-lookahead**: run full vs truncated-at-midpoint and assert **byte-identical** outputs for all bars ≤ trunc.
  - Quality gates (spec §11.1 subset): avg bars/session band, lag-1 autocorr < 0.3, return mean ~0, no cross-session.
- Iterate until `test_core.py` exits 0.

**Outputs**
- Console summary + small saved CSVs in `/tmp/` (POC-only) for quick inspection.

---

### Phase 2 — V1 App Development (repo scaffold + data audit + 2 engines)
**Goal:** build the real repo structure and CLI scripts around the proven core.

**User stories**
1. As a researcher, I can `pip install -r requirements.txt` and run the repo with no manual setup beyond data placement.
2. As a researcher, I can run `python scripts/run_data_audit.py` and obtain all required reports for all 9 instruments.
3. As a researcher, I can run `python scripts/run_engines.py --engine vol_budget --symbol ES` and generate synthetic bar CSVs.
4. As a researcher, I can open `reports/data_integrity_summary.md` and see a one-page PASS/FAIL verdict per instrument.
5. As a researcher, I can read `reports/engine_diagnostics/*.md` and understand synthetic bar behavior per engine.

**Steps**
- Create repo tree exactly per spec §4 under `/app/sfpe_5m/`.
- Add configs (exact spec §3 where required):
  - `config/instruments.yaml`, `config/session_calendars.yaml`, `config/portfolio.yaml`
  - Stub `default_search_space.yaml`, `validation_policy.yaml` (placeholders only for v1)
- Implement core modules:
  - `src/sfpe/data/{schema,calendar,loader,integrity,roll_detection}.py`
  - `src/sfpe/synthetic/base.py`
  - `src/sfpe/synthetic/vol_budget.py` (Engine C)
  - `src/sfpe/synthetic/dollar_imbalance.py` (Engine A)
  - Stubs for `volume_time.py` and `range_budget.py` raising NotImplementedError.
- Implement CLI scripts:
  - `scripts/run_data_audit.py` → writes the 4 audit artifacts.
  - `scripts/run_engines.py` → runs Engine A/C across selected symbols and writes synthetic CSVs.
  - `scripts/run_pipeline.py` → runs audit + engines end-to-end for all instruments.
- Reporting artifacts:
  - `reports/data_integrity_summary.md`
  - `reports/data_integrity_by_instrument.csv`
  - `reports/roll_candidates.csv`
  - `reports/session_coverage_heatmap.png`
  - `reports/engine_diagnostics/{engine}_{symbol}.md` (at least ES, MES, MNQ)
- Document quirks + defaults in `BLOCKERS.md` (notably MGC 08:20 bars vs spec start; policy = exclude pre-RTH, count + report).

---

### Phase 2.5 — V1 Testing & Stabilization
**Goal:** lock correctness (especially causality) and produce a stable v1.

**User stories**
1. As a researcher, `pytest` passes consistently and catches regression in causality.
2. As a researcher, truncation/no-lookahead tests fail loudly if any future leakage is introduced.
3. As a researcher, audit outputs are reproducible run-to-run.
4. As a researcher, synthetic outputs are reproducible from the same config.
5. As a researcher, I can re-run the full pipeline and see clear PASS/FAIL gates for v1 scope.

**Steps**
- Add pytest suite:
  - `tests/test_data_integrity.py`
  - `tests/test_synthetic_engines.py`
  - `tests/test_no_lookahead.py` (mandatory)
- Run `python scripts/run_pipeline.py` and validate artifacts exist + basic sanity.
- Create `reports/v1_summary.md` listing:
  - What’s implemented (Phase 0–2 partial)
  - What’s deferred (Engines B/D, features, projections, backtest, walk-forward, Pine)
  - Any instruments with audit FAIL and why.
- Update `README.md` with exact run commands.

---

### Phase 3 — Next versions (captured now; implemented after v1)
**User stories**
1. As a researcher, I can generate Engines B/D synthetic bars and compare distributions across engines.
2. As a researcher, I can compute structural features (absorption, VPIN proxy, TPO, liquidity vacuum).
3. As a researcher, I can generate forward projections per engine and ensemble them.
4. As a researcher, I can backtest causally with realistic costs/slippage.
5. As a researcher, I can run fast walk-forward (12/3/3/1) and get a PASS/FAIL report.

**Scope roadmap**
- v2: Engines B + D + Phase 3 feature modules
- v3: Forward projection + ensemble
- v4: Backtest engine + baselines + cost models
- v5: Walk-forward fast protocol + stability checks
- v6: Final reporting + verdict
- v7 (only if v6 PASS): Pine v6 templates populated from WF params

## 3) Next Actions (immediate)
1. Implement and run **`scripts/test_core.py`** on ES until fully green.
2. Create repo scaffold + configs + core data modules.
3. Build `run_data_audit.py` and generate audit reports for all 9 instruments.
4. Implement Engine C + A and `run_engines.py` + diagnostics.
5. Add pytest tests and run the full pipeline.

## 4) Success Criteria
### POC success
- `python scripts/test_core.py` returns exit code 0 and prints OK for:
  - loader derivations
  - integrity checks
  - roll detection
  - engine A/C generation
  - **no-lookahead equivalence**
  - basic synthetic quality gates

### v1 success
- Repo matches spec structure; configs present.
- `python scripts/run_data_audit.py` produces all required artifacts.
- `python scripts/run_engines.py` produces synthetic CSVs for Engine A/C.
- `pytest` passes (including no-lookahead).
- `reports/v1_summary.md` clearly states v1 scope + deferred work.
- No Pine code generated.