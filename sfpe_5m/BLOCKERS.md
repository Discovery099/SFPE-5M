# BLOCKERS — documented decisions when spec was ambiguous

This file records every decision made when the SFPE-5M v2 spec did not unambiguously dictate a value or policy. Each entry: **question**, **chosen default**, **rationale**, **where it lives in code**.

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
- **Default:** Bootstrap `theta_t` from a causal rolling mean of `|source_bar_signed_notional|` over `imbalance_window` past source bars, scaled by `sqrt(expected_bars_per_session / target_bars_per_session)`. This is the stopped-random-walk scaling for first-hit threshold to land near the target bars-per-session.
- **Rationale:** Random-walk stopping theory: for iid increments with mean absolute deviation `m`, hitting threshold `b` takes ~ (b/m)² steps in expectation. Setting `b = m × sqrt(N_target)` yields ~N_target steps per synthetic.
- **Code:** `src/sfpe/synthetic/dollar_imbalance.py::DollarImbalanceEngine.run`.
- **Spec §11.1 gate:** Verified on ES → avg 8.4 bars/session, lag-1 autocorr 0.002 (PASS).

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
- **Code:** every engine's main loop. Acceptance gate spec §11.1 verified: 0 cross-session synthetic bars.

## 8. ATR_20 cold start at session open
- **Question:** ATR_20 is a session-aware EMA. What initial value at the first bar of each session?
- **Default:** Reset to the first bar's true_range (which at session open equals high-low, since no prior same-session close exists). EMA proceeds from there with span=20.
- **Code:** `src/sfpe/data/loader.py::_session_aware_ema`.

## 9. Roll detection threshold
- **Question:** Spec §5.3 sets `gap > 5.0 × ATR_20` as the roll flag. Should this also use prior-day ATR_20 (causal) or current-day open?
- **Default:** Prior-day ATR_20 at the close of session N (fully causal). Reported in `reports/roll_candidates.csv`.
- **Code:** `src/sfpe/data/roll_detection.py`.

## 10. Pine Script
- **Question:** Spec §18 rule #10 forbids Pine generation until full walk-forward PASS. v1 has no walk-forward.
- **Default:** v1 generates NO Pine code. Module `src/sfpe/export/pine_generator.py` is a stub raising `NotImplementedError("Phase 8: requires walk-forward PASS verdict")`.
- **Code:** `src/sfpe/export/pine_generator.py`.

## 11. testing_agent_v3 vs pytest for v1
- **Question:** E2 mandate calls for `testing_agent_v3`. This is a CLI-only research repo (no web UI, no API, no browser).
- **Default:** Use `pytest` + `scripts/test_core.py` for verification in v1. `testing_agent_v3` is a browser/curl automation agent and does not apply to this project's surface area.
- **Code:** `tests/`.
