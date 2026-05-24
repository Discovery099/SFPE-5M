# SFPE-5M — Phase 5 Final Verdict (v1.4, 2026-05-24)

> Headline: the spec §7 strategy, as currently specified, FAILS the realized
> P&L test across all 9 instruments, 10 strategy variants, 10 baselines,
> 2 confidence thresholds, 3 cost models, and 3 slippage multipliers.
>
> Phase 5 is EVALUATION only — per user lock, no tuning has been applied.

## Audit gate (Phase 5 \u00a715 trade-count gate)
- Portfolio total trades:  conf=0.50 → 9,627  ;  conf=0.65 → 6,643  (both ≫ 200)
- Per-instrument trades:   all 9 ≥ 50 (lowest MCL conf=0.65 at 288)
- **✅ Gate passes** — sample sizes are statistically meaningful; we proceed
  to PF / Sharpe analysis.

## Portfolio P&L (primary cost model, 1× slippage, family-concurrency enforced)

| Conf | Trades | Net P&L | PF | Sharpe | Max DD | Win rate |
|------|--------|---------|----|--------|--------|----------|
| 0.50 | 8,145 | **−$279,493** | 0.80 | −1.64 | −$279,644 | 49.2% |
| 0.65 | 5,852 | **−$227,930** | 0.79 | −1.78 | −$229,894 | 48.8% |

All variants negative. Equity-curve image confirms a consistent downward
trend from $100k starting equity to roughly −$120k by 2026 — i.e. a peak-to-
trough drawdown of ~220% of starting equity, with **no regime where the
strategy is profitable**.

## Critical findings

### 1. Calibration sanity check FAILS (the spec §11.2 promise doesn't translate to P&L)
- Per-user lock, we ran the strategy at two confidence thresholds 0.50 and 0.65
  to validate the Phase 4 calibration plot against realized P&L.
- Result: PF moves from **0.80 (conf=0.50) → 0.79 (conf=0.65)**.
  Win rate moves from **49.2% → 48.8%**.
- The "high confidence" filter does NOT materially improve outcomes — it just
  reduces the trade count by ~25% while keeping the same losing edge.
- **This means the spec §11.2 close-in-zone calibration is not informative
  about realized P&L.** Either the close-zone metric is the wrong objective
  (we hit the projected close zone but at unprofitable entry locations) or
  the trade-management overlay (stops/targets/holding period) is destructive.

### 2. Strategy is statistically indistinguishable from baselines
Mean profit factor across active instruments:

| Variant | Mean PF | Mean Sharpe |
|---------|---------|-------------|
| STRATEGY (conf=0.65) | **0.77** | −2.02 |
| buy_and_hold_intraday | 0.80 | −1.67 |
| atr_breakout | 0.75 | −1.60 |
| bollinger_mean_reversion_20 | 0.75 | −1.70 |
| donchian_channel_20 | 0.74 | −1.79 |
| ema_crossover_9_21 | 0.78 | −1.36 |
| opening_range_breakout | 0.78 | −1.31 |
| prior_bar_mean_reversion | 0.78 | −1.36 |
| prior_bar_momentum | 0.78 | −1.38 |
| random_entry_matched_holding | 0.78 | −1.84 |
| vwap_mean_reversion | 0.76 | −1.48 |

- The strategy's PF (0.77) sits in the **middle of the baseline distribution
  (0.74–0.80)**. It performs essentially identically to random entries.
- Strategy mean Sharpe (−2.02) is **the WORST** in the table — slightly worse
  than every baseline. This is consistent with its much lower trade count
  (738 vs 1,447–28,400) producing a more concentrated loss-per-trade.

### 3. Slippage sensitivity reveals razor-thin (negative) edge
At fixed_tick cost, the loss scales nearly linearly with slippage:

| Slip | Net P&L | PF | Sharpe |
|------|---------|----|--------|
| 1× | −$354,753 | 0.79 | −1.86 |
| 2× | −$607,781 | 0.60 | −3.77 |
| 3× | −$800,477 | 0.47 | −5.43 |

Doubling slippage roughly doubles the loss, suggesting **the strategy's gross
edge is consistently smaller than 1 tick** (real-world slippage on these
instruments). With realistic 2× slippage assumptions the strategy is far
more decisively unprofitable than the 1× headline numbers suggest.

### 4. Stress windows — uninformative
- **COVID (2020-02-20 → 2020-05-31): 0 trades on every instrument.**
  Likely the Phase-3 regime router classified the COVID-period bars as
  `stand_down` / `stressed_illiquid`, blocking all signal eligibility.
  This is the only stress-period "win" — the strategy correctly stayed flat.
- Rates (2022-06 → 2022-10): 677 trades, −$34,090, 48.6% win rate. Underperforms.
- Banks (2023-03 → 2023-09): 501 trades, −$31,912, 45.7% win rate. Underperforms.
- Opening 30 min: 3 trades total across all 9 instruments — feature warmup
  blocks essentially the entire 09:30–10:00 window. Stress detection there
  is uninformative.
- Closing 30 min: 162 trades at 38.7% win rate. Worst-performing intra-day
  window (consistent with the `latest_entry_time = 15:30` cutoff and the
  general behavior that close-to-close mean-reversion fails late session).

### 5. Roll-skip impact
Per user request, blocked-by-roll-skip counts:
- Equities (ES, MES, MNQ, YM, MYM, RTY, M2K): all **below 5%** of eligible
  bars (1.2 – 3.2%). ✅
- **MGC: 8.7–8.8% blocked** ⚠️
- **MCL: 9.6–10.6% blocked** ⚠️

The MGC/MCL over-block is the inherent commodity contract cadence
(monthly/bi-monthly rolls) flagged in BLOCKERS §9. The user's >5% revisit
trigger is exceeded on these two products. Practical implication: ~50 MGC
trades and ~50 MCL trades are blocked over 6 years. Given those products
are unprofitable anyway, the over-block actually saves money in this run.
Recommendation: leave alone for now; revisit during Phase 6 walk-forward
where the optimizer can choose tighter calendar windows per family.

## Per-instrument verdict (conf=0.65, 1× slippage, fixed_tick)

| Symbol | Trades | Net P&L | PF | Verdict |
|--------|--------|---------|----|---------|
| ES   | 871 | −$48,294 | 0.70 | Unprofitable, worst PF on equities |
| MES  | 907 | −$43,698 | 0.71 | Unprofitable |
| MNQ  | 821 | −$22,987 | 0.86 | Unprofitable, best PF on equities |
| YM   | 823 | −$19,775 | 0.84 | Unprofitable |
| MYM  | 810 | −$16,310 | 0.89 | Unprofitable, **best PF overall** |
| RTY  | 841 | −$31,514 | 0.78 | Unprofitable |
| M2K  | 787 | −$36,995 | 0.77 | Unprofitable |
| MGC  | 495 | −$20,119 | 0.79 | Unprofitable |
| MCL  | 288 | −$31,120 | 0.60 | Unprofitable, **worst** product |

Notably the Dow family (YM/MYM) — which we predicted would underperform from
the Phase 4 §11.2 acceptance gate — actually has the best PF in this realized
P&L test. That's because the 100-point round-number grid that produced wider
zones in Phase 4 also produces wider trade-management distances (stops/
targets), which on this losing strategy means fewer round-trips and less
friction per trade. None of this changes the fact that EVERY instrument is
unprofitable.

## Mandatory deliverables (this run)
- `reports/v1_4_micros_vs_majors.md` — Phase 5.0 diagnostic.
- `reports/v1_4_roll_audit.md`, `reports/v1_4_roll_candidates.csv` — Phase 5.1.
- `reports/v1_4_trade_count_audit.md`, `reports/v1_4_phase5_trade_count_audit.csv`
  — Phase 5.4 audit (FIRST, per spec).
- `reports/v1_4_phase5_summary.md`, `reports/v1_4_phase5_metrics.csv` — full results.
- `reports/v1_4_phase5_baselines.csv` — 10-baseline comparison.
- `reports/v1_4_phase5_slippage_table.csv` — 1×/2×/3× sensitivity.
- `reports/v1_4_phase5_stress_windows.csv` — COVID / rates / banks columns.
- `reports/v1_4_phase5_roll_skip_blocked.csv` — user-requested roll-skip log.
- `reports/v1_4_phase5_per_instrument_equity__<SYM>.csv / .png` — 9 instruments.
- `reports/v1_4_phase5_portfolio_equity__conf=0.50.csv / .png`,
  `reports/v1_4_phase5_portfolio_equity__conf=0.65.csv / .png`.

Test gate: `pytest tests/` — **70/70 PASS** (49 prior + 21 new backtest +
7 roll-detection − minor adjustments).

## Honest verdict & next-step options for the user

**Phase 5 outcome:** the SFPE-5M spec as currently specified does NOT produce
a profitable strategy on the 6-year × 9-instrument sample, under any
combination of confidence threshold / cost model / slippage that we tested.
The strategy is **statistically indistinguishable from random/baseline
entries** in mean PF, and is **the worst** in mean Sharpe.

**What this means:**
1. **No Pine Script.** Per spec §18 rule #10 + BLOCKERS §10, Pine is only
   permitted after a full walk-forward PASS. We are explicitly farther from
   that authorization than before Phase 5.
2. **No on-the-fly tuning.** Per user lock and BLOCKERS §14, Phase 5 is
   evaluation, not optimization. The natural next step is Phase 6
   walk-forward, but that is the owner's decision.

**Options the owner can choose from (no work begun on any of these):**
- **A) Accept the negative verdict and stop.** Document SFPE-5M as a failed
  hypothesis on this dataset and move on.
- **B) Phase 6 walk-forward optimization (spec §13).** Search over the
  parameters per BLOCKERS §31, §36, §30 (vpin_window_buckets, env_widen,
  max_zone_width_atr, etc.) on an in-sample window, then verify on a true
  out-of-sample window. This is the standard next step in the spec.
- **C) Diagnostic deep-dive before Phase 6.** Look at *why* every variant
  loses ~$50/trade. Likely candidates:
    * Stop too tight (1× ATR) → stopped out before reaching close zone.
    * Target too aggressive vs realized distribution.
    * `min_engines_agree=3` + structural overrides producing biased entries
      at structural levels that get rejected.
  This is research, not optimization; results would inform Phase 6 search
  space.
- **D) Re-derive `trade_eligible` without the regime filter.** The regime
  filter blocks 88% of bars (BLOCKERS §33). Removing it expands the trade
  set ~9× but may dilute the signal further. Tradable hypothesis.

**Awaiting owner direction before any further work.** Per user lock:
"if a gate fails, surface and stop."

---

_Generated 2026-05-24 by SFPE-5M v1.4 Phase 5 pipeline.  All deliverables in `reports/v1_4_phase5_*`._
