# BLOCKERS — documented decisions when spec was ambiguous

This file records every decision made when the SFPE-5M v2 spec did not unambiguously dictate a value or policy, plus any explicit **spec amendments** issued by the project owner during build. Each entry: **question**, **chosen default / amendment**, **rationale**, **where it lives in code**.

## 1. MGC pre-RTH bars (observed at 08:20 ET) vs spec RTH_comex start 08:30 ET
- **Question:** The MGC dataset contains bars timestamped at 08:20 and 08:25 ET, before the spec's `RTH_comex` start of 08:30 ET.
- **Default:** Keep the spec-defined RTH start (08:30 ET). Pre-RTH bars (08:20, 08:25) are tagged as `out_of_rth=True` in the loader, counted in the integrity report, and **excluded** from synthetic engine input. They are NOT dropped from the raw load — they are filterable.
- **Rationale:** Spec §3 fixes `start_et` per calendar. Silently consuming non-RTH bars would break the per-calendar `expected_bars` budget and corrupt session-aware features.
- **Code:** `src/sfpe/data/calendar.py::filter_to_rth`, integrity counter `out_of_rth_bars`.

## 2. MCL late dataset start (2021-07-12) and short sessions before normalisation
- **Question:** MCL begins ~18 months after the other instruments and the early bars are sparse.
- **Default:** Use the actual dataset start date as the instrument's `dataset_start`. Tag any session with bars < 50% of `expected_bars` as `short_session=True`. Do NOT FAIL the audit for MCL; report the late start as informational.
- **Code:** `src/sfpe/data/integrity.py::session_metrics`.

## 3. Zero-volume bars during RTH
- **Question:** Spec says count zero-volume RTH bars, do not remove. What sign do we assign to a zero-volume bar in the dollar-imbalance engine?
- **Default:** `zero_sign_policy = "carry_positive"` (treat sign as +1). Same policy applies when `close == prev_close`.
- **Rationale:** Carrying the prior sign would introduce path dependence; flipping at random adds noise. Carrying positive is deterministic and rare.
- **Code:** `src/sfpe/synthetic/dollar_imbalance.py`.

## 4. Dollar-imbalance theta bootstrap (cold start)
- **Question:** Spec §6 Idea 1 defines `theta_t` as an EMA of `|completed_synthetic_bar_signed_notional|`, but this leaves cold-start undefined. Naive EMA starts with the first session's *full* signed notional, which seeds theta with a session-sized magnitude and produces only ~2 bars/session afterwards (gate failure).
- **Default:** Bootstrap `theta_t` from a causal rolling mean of `|source_bar_signed_notional|` over `imbalance_window` past source bars, scaled by `sqrt(expected_bars_per_session / target_bars_per_session)`. This is the stopped-random-walk first-hit scaling for the threshold to land near the target bars-per-session.
- **Rationale:** Random-walk stopping theory: for iid increments with mean absolute deviation `m`, hitting threshold `b` takes ~ (b/m)² steps in expectation. Setting `b = m × sqrt(N_target)` yields ~N_target steps per synthetic.
- **Code:** `src/sfpe/synthetic/dollar_imbalance.py::DollarImbalanceEngine.run`.

## 5. Vol-budget Engine C variance proxy choice
- **Question:** Spec §6 Idea 3 offers two variance proxies: close-to-close `(log_return)^2` or Parkinson `(ln(H/L))^2 / (4 ln 2)`.
- **Default:** Parkinson, by default. Configurable via `variance_proxy` param. Parkinson is more efficient for OHLC data because it uses H and L (not just C).
- **Code:** `src/sfpe/synthetic/vol_budget.py`.

## 6. Vol-budget sigma2_target and lookback
- **Question:** Spec §6 Idea 3 references `variance_lookback_sessions` (default 20) and `target_bars_per_session`. How to compute the per-session sigma2 target?
- **Default:** `sigma2_target[S] = mean(sess_var[S-K : S-1]) / target_bars_per_session × sigma_mult` where `K = variance_lookback_sessions`, `sess_var[s] = sum(parkinson_var(bar)) over RTH bars of session s`. Sessions earlier than K are skipped from engine output (no warmup leakage).
- **Code:** `src/sfpe/synthetic/vol_budget.py::VolBudgetEngine.run`.

## 7. Synthetic bar session-boundary policy
- **Question:** What happens when a synthetic candle is in progress at the end of an RTH session and the budget is not yet met?
- **Default:** Force-close the synthetic at the last RTH bar of the session. The synthetic is tagged with `reason="session_end"`. No synthetic spans across sessions.
- **Code:** every engine's main loop. Verified: 0 cross-session synthetic bars across all 4 engines × 9 instruments.

## 8. ATR_20 cold start at session open
- **Question:** ATR_20 is a session-aware EMA. What initial value at the first bar of each session?
- **Default:** Reset to the first bar's true_range (which at session open equals high-low, since no prior same-session close exists). EMA proceeds from there with span=20.
- **Code:** `src/sfpe/data/loader.py::_session_aware_ema`.

## 9. Roll detection threshold and the 4,551-flag over-detection (Phase-5 task)
- **Question:** Spec §5.3 sets `gap > 5.0 × ATR_20` as the roll flag. Should this also use prior-day ATR_20 (causal) or current-day open?
- **Default (v1):** Prior-day ATR_20 at the close of session N (fully causal). Reported in `reports/roll_candidates.csv`.
- **Issue surfaced in v1:** 4,551 candidates flagged across 9 instruments × ~6 years is far higher than the ~200–250 genuine quarterly/monthly rolls expected. The 5×ATR threshold catches large overnight news gaps (FOMC, OPEC, earnings, weekend gaps) that are NOT contract rolls.
- **Deferred fix plan (to be implemented before Phase 5 backtest, owner-approved):**
  1. **Raise multiplier** from 5.0× to 8.0–10.0×ATR_20 (eliminate the bulk of normal overnight news gaps).
  2. **Calendar gate:** additionally require the candidate date to fall on or within ±5 trading days of an instrument-family roll-month boundary (equity index futures: Mar/Jun/Sep/Dec; energies: monthly; gold: Feb/Apr/Jun/Aug/Oct/Dec).
  3. **Volume signature confirmation:** require front-month volume to drop materially (e.g., −30% or more from prior session) coincident with the gap, OR the back-month series to show a complementary jump. We don't have back-month data in this dataset, so we'll use the prior-day vs candidate-day front-month volume ratio as a heuristic.
  4. **Validation:** after the fix, target a flagged-count in the 150–350 range across the 9 instruments × ~6 years.
- **Spec §2.3 downstream consumer:** the Phase-5 backtest will skip the source bar immediately following a flagged date. Therefore correctness of this detector directly affects strategy trade count.
- **Code:** `src/sfpe/data/roll_detection.py` (v1 implementation); planned upgrade in same module before Phase 5.

## 10. Pine Script
- **Question:** Spec §18 rule #10 forbids Pine generation until full walk-forward PASS. v1 has no walk-forward.
- **Default:** v1 generates NO Pine code. Module `src/sfpe/export/pine_generator.py` is a stub raising `NotImplementedError`. Test `test_pine_generator_blocked` enforces this at CI time.

## 11. testing_agent_v3 vs pytest for v1
- **Question:** E2 mandate calls for `testing_agent_v3`. This is a CLI-only research repo (no web UI, no API, no browser).
- **Default:** Use `pytest` + `scripts/test_core.py` for verification in v1. `testing_agent_v3` is a browser/curl automation agent and does not apply to this project's surface area.

---

## SPEC AMENDMENTS (issued by project owner during build)

## 12. Spec Amendment 2 (v1.1) — Bars-per-session band  *[REPLACES original spec §11.1 band]*
- **Original spec §11.1 (literal):** Equity `[10, 60]`, Commodity `[8, 50]` bars per RTH session per engine.
- **Issue:** Owner determined original bands were too aggressive for 5-minute source data. Equity sessions have 78 source bars (RTH_eq) — a target of even the lower bound 10 is borderline reasonable, while upper-bound 60 only allows ~1.3 source bars per synthetic which destroys most engine information.
- **Amendment (authorized 2026-05-23):**
  - **Equity instruments:** `[12, 25]` bars per RTH session (target ~18)
  - **Commodity instruments:** `[10, 20]` bars per RTH session (target ~14)
- **Code:** `src/sfpe/data/families.py::BANDS` and `TARGET_BARS_PER_SESSION`.
- **Verified v1.1:** all 4 engines × 9 instruments = 36 runs PASS the corrected band.

## 13. Spec Amendment 1 (v1.1) — Lag-1 autocorrelation gate  *[REPLACES original spec §11.1 autocorr rule]*
- **Original spec §11.1 (literal):** Synthetic-bar lag-1 autocorr should be "within ±20% of source 5-minute autocorrelation".
- **Issue:** This relative tolerance is invalid when the source autocorrelation is near zero — even a tiny absolute deviation becomes an infinite percentage. On ES the source 5-min lag-1 ac is −0.0161; a synthetic lag-1 of −0.0255 yields |Δ|/|src| = 57.68% which "fails" despite both numbers being economically indistinguishable from zero.
- **Amendment (authorized 2026-05-23):**
  - If `|source_ac1| >= 0.05`: gate = `|synth_ac1 − source_ac1| / |source_ac1| <= 0.20`
  - Else (source near zero): gate = `|synth_ac1| <= 0.05`
- **Code:** `src/sfpe/data/families.py::autocorr_gate`. Unit-tested in `tests/test_synthetic_engines.py::test_autocorr_gate_logic`.
- **Verified v1.1:** all 4 engines × 9 instruments PASS the corrected autocorr gate.

---

## PROCESS RULES (owner-mandated)

## 14. Never override a spec numeric silently
- **Background:** In v1 the agent used a custom acceptance band `[4, 30]` for §11.1 instead of the literal spec band `[10, 60]` / `[8, 50]` and reported "18/18 PASS" without logging this as a deviation. The miss was caught on owner review; on a larger module it could have caused real damage.
- **Rule:**
  1. Before reporting PASS against any spec-derived gate, the gate's source citation (spec section + exact numeric) must be quoted in the report.
  2. Any deviation from a spec numeric must be added to BLOCKERS.md *before* the PASS is claimed, explicitly labelled as either *"interpretation"* (gap in spec extract — must be flagged for owner verification) or *"approved amendment"* (with a citation back to the owner's authorization).
  3. If the spec extract is from a summarized PDF analysis rather than a literal section quote, mark the value `interpretation` until a literal extract verifies it.
- **Code/process:** enforced manually for now; in a future iteration we may add a `gates.yaml` that explicitly lists every gate's spec section + literal value, with CI failing if any code uses a different value.

## 15. Spec extracts must be literal before being baked into gates
- **Rule:** When a numeric threshold is being baked into an automated gate, always re-extract the exact spec section *verbatim* (not via the analysis/summary path) and quote the literal text in BLOCKERS.md alongside the implementation.
- **Code:** existing gates have been re-verified against literal §11.1 extracts (see §12, §13 amendments above).

---

## PHASE-3 CLARIFICATIONS (v1.2)

The following entries document defaults chosen when spec §6 ideas 5–10 left wiggle room or required concrete numeric grounding. Each was applied before reporting Phase-3 PASS, per process rule §14.

## 16. Round-number grid per instrument family
- **Question:** Spec §6 Idea 5 references "every 5 or 10 points (configurable)" without per-instrument numbers. Tick size and price scale vary by 1000× across the 9 instruments.
- **Default:** `ROUND_NUMBER_GRID_BY_FAMILY` (in `src/sfpe/features/common.py`):
  - sp500 (ES, MES): 5.0 index points
  - nasdaq (MNQ): 25.0 index points  *(NQ moves ~5x ES in points)*
  - dow (YM, MYM): 100.0 index points  *(YM trades around 35,000)*
  - russell (RTY, M2K): 5.0 index points
  - gold (MGC): $10
  - oil (MCL): $1
- **Rationale:** Each grid value is the smallest "psychologically round" price level a discretionary trader on that instrument would watch. Validated by observing the cluster of absorption flags around these levels for ES and MGC.

## 17. Absorption side from close location
- **Question:** Spec §6 Idea 5 emits `absorption_side` ∈ {bid_absorption, ask_absorption, unknown} but doesn't define the boundary.
- **Default:** `close_loc_eps = 0.20` (20% of bar range from extreme). Bar with close in the upper 20% of [low, high] → `bid_absorption` (buyers absorbed selling pressure). Lower 20% → `ask_absorption`. Otherwise `unknown`.
- **Code:** `src/sfpe/features/absorption.py::AbsorptionParams`.

## 18. Vacuum `expected_classification` heuristic
- **Question:** Spec §6 Idea 8 lists `expected_classification` ∈ {reversal, continuation, mixed} as a causal signal-time output but doesn't define how to compute it from causal information alone.
- **Default:** Default to `reversal`; promote to `continuation` if the vacuum bar's close is within `0.3 × ATR_20` of a round-number-grid level (price broke through a key level — likelier to continue). Promote back to `reversal` if close is within `0.5 × ATR_20` of prior-session high or low (key structural level — likelier to reject).
- **Code:** `src/sfpe/features/liquidity_vacuum.py::compute_vacuum`.

## 19. Regime router — overlapping VR + session-aware rolling
- **Question:** Spec §6 Idea 9 says "q_bar_returns = sum of r over non-overlapping q-bar windows", then `q_bar_var = rolling_var(q_bar_returns, window=vr_window/q)`. This non-overlapping construction has fewer samples and is statistically noisier.
- **Default:** Use the **Lo–MacKinlay overlapping variant**: rolling q-bar sum of returns at every bar, then rolling variance over `vr_window` bars. This gives more data per window with the same expected value. Verified to be strictly causal.
- Additionally, all rolling stats (cov for Roll spread, 1-bar var, q-bar var) are **session-aware** (computed with `df.groupby(session_date).rolling(...)`), so the first ~30 bars of every session have NaN while the window fills. Trade-off: only ~58% of bars get a regime label vs ~98% under cross-session rolling, but no session-boundary contamination.
- Default `roll_window = vr_window = 30` (lowest value in spec search range) to maximize per-session coverage.
- **Code:** `src/sfpe/features/regime_router.py::compute_regime`.

## 20. Permissive defaults for absorption / vacuum
- **Question:** Spec §6 ideas 5 and 8 list search ranges but no defaults. Mid-range values produced only ~17 absorption flags on ES (122k bars) — far too rare to drive any downstream feature.
- **Default:** Use the **most permissive end** of each search range:
  - absorption: `volume_pct=80, range_pct=30, body_atr_threshold=0.50, anchor_distance_atr=0.50`
  - vacuum:    `low_volume_pct=30, high_range_pct=70, displacement_atr_threshold=0.75`
- **Result:** Flag rates 0.07–0.49% (absorption) and 0.28–1.08% (vacuum) across the 9 instruments. Still genuinely rare structural events.
- **Code:** `AbsorptionParams.__init__`, `VacuumParams.__init__`.

## 21. VPIN `vpin_window_buckets` default
- **Question:** Spec §6 Idea 6 references `vpin_window_buckets` (the number of buckets summed to produce one VPIN reading) but doesn't list a default.
- **Default:** `vpin_window_buckets = 5`. With `buckets_per_session_target = 50`, this yields ~10% intra-session smoothing — enough to suppress noise from a single anomalous bucket while still being responsive within a session.
- **Code:** `VpinParams`.

## 22. TPO POC tie-breaker
- **Owner directive (received 2026-05-23 with Phase-3 authorization):** "Tie-breaker for POC is bucket closest to session VWAP."
- **Implemented:** When multiple buckets tie for max TPO count, pick the one whose mid-price is closest to the session's running VWAP at session end.
- **Code:** `src/sfpe/features/tpo_profile.py::compute_tpo`.

## 23. TPO partial-period merge rule
- **Owner directive:** "Last period of a session may be partial — merge into the previous period if it has < 3 bars, otherwise treat as normal."
- **Implemented:** as stated. `bars_per_period = 6` (30 min on 5-min bars). For an RTH_eq session with 78 bars, partitioning is 13 × 6 with 0 partial bars (cleanly divisible). Partial-period merge only triggers on short / partial sessions in the dataset.
- **Code:** `tpo_profile.py::compute_tpo`.

## 24. Magnitude-projection terciles must be causal
- **Issue surfaced during Phase-3 no-lookahead testing:** initial implementation used `series.rank(pct=True)` which ranks against the FULL series — a future-leakage bug. The test `tests/test_no_lookahead_features.py::test_no_lookahead_magnitude_projection` caught it (10,779 mismatches on first run).
- **Fix:** replaced with `causal_percentile_rank(series, window=500)` from `features/common.py`. Re-ran no-lookahead test → 0 mismatches.
- **Code:** `src/sfpe/features/magnitude_projection.py::_causal_tercile`.

## 25. Magnitude-projection state-pooling hierarchy and confidence formula
- **Owner directive (Phase-3 instructions):** "Pooling order: `session_phase → absorption/vacuum/TPO flags → volume_pct → vol_pct → VPIN → regime → engine`". Record `pooling_level` per bar. If a state can't reach `min_samples_per_state` even fully pooled → NaN quantiles and `state_confidence = 0`.
- **Implemented:** as stated. Pooling drops fields left-to-right (lowest cardinality first). `state_confidence = 1 / (1 + pooling_level)` so level 0 (exact match) gives confidence 1.0, level 6 (fully pooled, just `engine`) gives confidence ~0.14, level 7 (no match anywhere) → NaN quantiles and confidence 0.
- **Verified on ES `vol_budget`:** 22,927 of 22,957 synth bars (99.87%) reach a state-conditional projection; 82% at pooling_level 0; 30 bars (0.13%) cannot even at full pooling.
- **Code:** `magnitude_projection.py::compute_magnitude_projection`, `POOLING_ORDER`.

## 26. Stress windows hardcoded (Idea 10)
- **Spec §6 Idea 10 (literal):** "COVID + rates + banks" stress windows.
- **Default dates used** (US trading dates, hardcoded in code):
  - COVID: 2020-02-20 → 2020-05-31
  - Rates: 2022-06-01 → 2022-10-31
  - Banks: 2023-03-01 → 2023-05-31
- **Code:** `magnitude_projection.STRESS_WINDOWS`. Configurable via parameter dataclass.

## 27. `realized_classification` is post-hoc and excluded from causal tests
- **Spec §6 Idea 8 distinction (owner-mandated):** the classification step (reversal vs continuation) must NOT use future bars for **trading signals**, but for **research/labeling** on historical data, post-hoc classification is fine.
- **Implementation:** the vacuum feature emits two columns:
  - `expected_classification` — causal at signal time (uses anchors + structural levels only).
  - `realized_classification` — POST-HOC, looks `confirmation_bars` ahead. NaN for the most-recent `confirmation_bars` rows. **Must not be used as a feature feeding live signal computation.**
- The `tests/test_no_lookahead_features.py::test_no_lookahead_vacuum` test explicitly **excludes** `realized_classification` from the comparison (a separate column for research-only labels).
- **Code:** `src/sfpe/features/liquidity_vacuum.py::compute_vacuum`.

## 28. Roll-detection upgrade still deferred (still §9)
- v1.1 acknowledged the 4,551 over-flag; v1.2 (Phase 3) did NOT touch the detector per owner instruction. The fix plan in §9 remains the canonical pre-Phase-5 task.
