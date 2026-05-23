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
