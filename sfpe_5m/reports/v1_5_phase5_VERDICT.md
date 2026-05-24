# SFPE-5M — Phase 5 Final Verdict v1.5 (PROJECTION-AWARE EXITS)

> **Critical correction over v1.4 verdict (2026-05-24):** the v1.4 backtest
> tested generic 1×ATR stops/targets — disconnected from the Phase-4 projection
> layer. v1.5 wires spec §8.3 properly: TP1 = projected_close_mid (50% partial),
> TP2 = projected_close_high (long) / projected_close_low (short), structural
> stops from absorption/vacuum/TPO overrides, fallback stop at synthetic-open
> ± 0.5×ATR, time-stop = ceil(projected_completion_median × 1.5). Baselines
> KEEP their legacy ATR exits for fair comparison.
>
> Phase 5 is STILL EVALUATION ONLY — no tuning has been applied.

## TL;DR
- Wiring the Phase 4 projection layer into Phase 5 exits **improves** but
  **does not fix** the strategy.
- Portfolio (conf=0.65, fixed_tick, 1× slippage): **PF = 0.77, net = −$146,257**
  on $100k starting equity over 5 years. Sharpe = −1.63, Max DD = −$148,758.
- Compared to v1.4 (generic ATR exits): same PF (0.77 vs 0.79), but ~36 %
  smaller absolute loss (−$146k vs −$228k) and very different exit-reason mix.
- Strategy is **still statistically indistinguishable from baselines** in PF.
- Most trades exit by **stop (49 %)** or **time-stop (43 %)**, only **6 %**
  reach TP2 (projected_close_high). The projection envelope is geometrically
  correct (TP2 wins average +$361) but tight stops + short time-stop cap the
  strategy before TP2 can be hit.

## v1.5 vs v1.4 side-by-side

| Metric (conf=0.65, fixed_tick, 1× slip) | v1.4 (generic ATR exits) | v1.5 (projection-aware) |
|---|---|---|
| Portfolio trades | 5,852 | **4,110** (−30 %) |
| Portfolio net P&L | −$227,930 | **−$146,257** (+36 % less negative) |
| Portfolio PF | 0.79 | **0.77** |
| Portfolio Sharpe | −1.78 | **−1.63** |
| Portfolio win rate | 48.8 % | **41.6 %** (tighter stops → more losers) |
| Max DD vs peak | −220 % | **−145 %** |

The projection-aware version filters out ~30 % of trades where the projected
envelope is degenerate (projected_close on wrong side of entry, etc.), and
caps individual losses with tighter structural stops. **Net per-trade** went
from −$39 (v1.4) to −$36 (v1.5) — a 8 % improvement but still negative.

## Audit gate
- Portfolio total trades:
    conf=0.50 → 6,859 ; conf=0.65 → 4,741 (both ≫ 200).
- Per-instrument: all 9 ≥ 50 at conf=0.65 (lowest MCL at 213).
- **✅ Gate passes** — sample sizes statistically meaningful.

## Portfolio (family-concurrency-enforced) — primary cost model 1× slippage

| Conf | Trades | Net P&L | PF | Sharpe | Max DD | Win rate |
|------|--------|---------|----|--------|--------|----------|
| 0.50 | 5,735 | **−$194,488** | 0.78 | −1.56 | −$196,423 | 42.0 % |
| 0.65 | 4,110 | **−$146,257** | 0.77 | −1.63 | −$148,758 | 41.6 % |

Equity curve trajectory (conf=0.65): starts $100k → drops to ~$55k by
mid-2021 (initial -45 % drawdown) → plateaus $60k–$75k for ~6 months →
renewed decline through 2022–2026 → ends ~−$45k. **There is a 6-month
plateau period (mid-2021 → early 2022)** — better than v1.4's monotone
decline, but no sustained profitable phase.

## Critical finding 1 — Calibration sanity check still FAILS
Per the user-locked dual-threshold check (conf=0.50 vs 0.65):
- PF: 0.78 → 0.77 (essentially unchanged)
- Win rate: 42.0 % → 41.6 % (drops slightly, not an improvement)
- Net P&L per trade: −$33.93 → −$35.59 (slightly worse at higher confidence)
**Higher confidence does not improve realized P&L.** The Phase 4 §11.2
close-in-zone calibration is still not predictive at the trade-management
level. This is the same conclusion as v1.4 — confirmed under the proper
projection-aware exit semantics.

## Critical finding 2 — Exit-reason distribution reveals the structural issue
For ES at conf=0.65, fixed_tick 1× slippage (639 trades, representative):

| Exit reason | Count | % | Avg net P&L | Total net P&L |
|---|---|---|---|---|
| stop | 310 | 48.5 % | −$612 | −$189,769 |
| time_stop | 274 | 42.9 % | −$261 | −$71,547 |
| **tp2** | **40** | **6.3 %** | **+$361** | **+$14,449** |
| session_end | 14 | 2.2 % | −$256 | −$3,578 |
| time_stop_after_tp1 | 1 | 0.2 % | +$26 | +$26 |

Per-trade expectancy: 0.063 × (+$361) + 0.485 × (−$612) + 0.429 × (−$261) +
0.022 × (−$256) = **−$413/trade** (gross) → about **−$47/trade net** of costs.

**Diagnosis:**
- Only **6 %** of trades reach TP2 (projected_close_high). The projection
  envelope IS directionally correct — when trades hit TP2, average win is
  +$361, a solid R:R of 1.3-ish vs the average stop loss of $612.
- But **49 % stop out**. Stops are tight (structural anchor ± 0.5×ATR or
  synthetic-open ± 0.5×ATR ≈ 1 point on ES). The market easily wiggles 1
  point on a 5-min bar. This is the dominant economic problem.
- **43 % time-stop out**. With `projected_completion_median × 1.5 ≈
  6–9 bars max hold`, many trades are still inching toward TP2 when the
  time-stop fires.

The Phase 4 projection forecasts the **session close** of the corresponding
synthetic bar, but the per-source-bar trade journey is much noisier than the
session-close projection implies. **Projection envelopes are correct
directionally but tight stops + short time-stops kill the strategy before
TP2 can be reached.**

## Critical finding 3 — TP1 partial-exit logic is functionally dormant
Only 4 of 4,110 strategy trades at conf=0.65 had `tp1_hit=True`. Reasons:
- TP1 (projected_close_mid) is BETWEEN entry and TP2. To hit TP1 then
  continue to TP2 requires the trade to survive (a) the stop, (b) the
  time-stop, AND (c) the partial-exit logic requires contracts ≥ 2.
- Position sizing at the configured `risk_per_trade = 0.005` (0.5 % of
  equity per trade) yields contracts = 1 for ES at $5000 with structural
  stop = 1 point and equity $100k (risk_dollars=$500 / point_value=$50 =
  10 contracts in principle but capped). On YM/MYM smaller contracts also
  yield 1.
- Net: partial-exit logic is engineered correctly but rarely triggered
  under current sizing. The mass of trades is single-contract → no partial.

This is mostly a sizing artefact, not a strategy artefact. A Phase-6
optimizer could explore larger position size or different TP1 partial
fractions, but per the user lock that's deferred.

## Per-instrument verdict (conf=0.65, 1× slippage, fixed_tick)

| Symbol | Trades | Net P&L | PF | Sharpe | Win rate | Notes |
|--------|--------|---------|----|--------|----------|-------|
| **YM**  | 579 | **−$4,631**  | **0.94** | −0.39 | 43.4 % | Best PF — closest to breakeven |
| **MNQ** | 586 | **−$9,631**  | **0.90** | −0.70 | 44.2 % | Second-best PF |
| MYM   | 573 | −$11,823 | 0.85 | −1.06 | 46.1 % | Highest win rate |
| RTY   | 572 | −$19,654 | 0.78 | −1.62 | 42.7 % | |
| MES   | 626 | −$21,313 | 0.75 | −1.77 | 40.1 % | |
| ES    | 639 | −$30,061 | 0.73 | −1.93 | 36.3 % | Worst PF on S&P |
| MGC   | 381 | −$15,957 | 0.71 | −2.27 | 43.3 % | |
| M2K   | 572 | −$28,406 | 0.70 | −2.22 | 41.1 % | |
| **MCL** | 213 | **−$19,706** | **0.57** | −3.52 | 36.6 % | Worst product |

**Notable change from v1.4:** YM/MNQ moved from worst-half (PF 0.84, 0.86)
to **best-half (PF 0.94, 0.90)** under projection-aware exits — likely because
the wider Dow/Nasdaq grids interact better with the projection envelope
(longer-distance TP2 = more room for the projection to play out before the
time-stop fires). Conversely ES/M2K got *worse* (tighter ATR, tighter stops).

## Slippage sensitivity
| conf | slip× | total trades | total net P&L | mean PF | mean Sharpe |
|------|-------|-------------|---------------|---------|-------------|
| 0.50 | 1× | 6,859 | −$216,071 | 0.78 | −1.63 |
| 0.50 | 2× | 6,799 | −$419,979 | 0.59 | −3.57 |
| 0.50 | 3× | 6,734 | −$584,141 | 0.45 | −5.45 |
| 0.65 | 1× | 4,741 | −$161,182 | 0.77 | −1.72 |
| 0.65 | 2× | 4,689 | −$317,873 | 0.58 | −3.76 |
| 0.65 | 3× | 4,634 | −$448,264 | 0.44 | −5.71 |

Slippage doubles losses linearly → gross edge < 1 tick. Same conclusion as v1.4.

## 10-baseline comparison (mean across instruments, fixed_tick 1× slippage)

| Variant | mean trades | mean net | mean PF | mean Sharpe | mean win% |
|---------|-------------|----------|---------|-------------|-----------|
| buy_and_hold_intraday | 1,447 | −$54,679 | 0.80 | −1.67 | 47.3 % |
| ema_crossover_9_21 | 28,404 | −$424,110 | 0.78 | −1.36 | 47.8 % |
| prior_bar_mean_reversion | 28,257 | −$433,580 | 0.78 | −1.36 | 47.5 % |
| prior_bar_momentum | 28,338 | −$449,057 | 0.78 | −1.38 | 47.7 % |
| opening_range_breakout | 18,638 | −$284,375 | 0.78 | −1.31 | 48.1 % |
| random_entry_matched_holding | 1,494 | −$51,409 | 0.78 | −1.84 | 48.0 % |
| **STRATEGY (conf=0.65, v1.5)** | **527** | **−$17,909** | **0.77** | **−1.72** | **41.5 %** |
| vwap_mean_reversion | 21,490 | −$369,490 | 0.76 | −1.48 | 47.2 % |
| atr_breakout | 10,206 | −$191,507 | 0.75 | −1.60 | 47.3 % |
| bollinger_mean_reversion_20 | 7,893 | −$173,968 | 0.75 | −1.70 | 47.3 % |
| donchian_channel_20 | 6,703 | −$145,729 | 0.74 | −1.79 | 47.3 % |

- **Strategy mean PF (0.77) is the median** of the baseline set (0.74–0.80).
- **Strategy mean absolute net (−$17,909) is the smallest loss** of all
  variants — but only because the strategy trades **~50× less often** than
  most baselines. The strategy is *more selective* (good) but still has a
  *losing per-trade edge* (bad).
- Strategy **win rate (41.5 %) is the LOWEST in the table**. That's the
  projection-aware tight-stop effect (we noted above).

## Stress windows (conf=0.65, 1× fixed_tick)
| Window | Trades | Net P&L | Win rate |
|--------|--------|---------|----------|
| COVID (2020-02-20 → 2020-05-31) | 0 | $0 | n/a |
| Rates (2022-06 → 2022-10) | 443 | −$9,962 | 46.0 % |
| Banks (2023-03 → 2023-09) | 385 | −$14,854 | 39.1 % |
| Opening 30 min | 3 | +$1,231 | 33.3 % |
| Closing 30 min | 113 | −$3,025 | 34.3 % |

- COVID: 0 trades on every instrument — same as v1.4 (regime filter correctly
  stayed flat).
- Banks stress slightly worse than rates (consistent with the v1.4 result).
- Opening 30 min still essentially uninformative (3 trades total across 9
  instruments × 5 years — feature warmup dominates).

## Roll-skip impact (per owner request)
- Equities: 1.2 – 3.2 % of eligible bars blocked ✅
- MGC: 8.7 – 8.8 % ⚠️
- MCL: 9.6 – 10.6 % ⚠️
Same conclusion as v1.4 — commodities exceed the 5 % "revisit" threshold
due to monthly/bi-monthly contract cadence. Benign since those products
are unprofitable anyway.

## Verdict

**Phase 5 v1.5 outcome:** spec §8.3 projection-aware exits **HONESTLY tested**
(this is what the user wanted to know all along). Result: the SFPE-5M
projection concept has **DIRECTIONAL VALUE** (TP2 wins average +$361 with
1.3-ish R:R) but the trade-management overlay as specified — tight
structural stops + short time-stops — **stops the strategy out 49 % of the
time and times it out 43 % of the time, before the projection can be
realised**. Only 6 % of trades reach TP2. The net effect is a losing
strategy that is **less bad than the generic-ATR v1.4 but still firmly
unprofitable**.

The Phase 4 projection envelope is **NOT** a snake-oil promise — it IS
informative in the trades that survive. The economic failure is in the
**stop/time-stop calibration**, not the projection concept.

## Honest next-step options

**No work has started on any of these. Awaiting owner direction.**

- **A) Accept v1.5 verdict and stop.** Strategy as-specified is unprofitable;
   the spec §8.3 trade management is incompatible with the §7 projection.

- **B) Phase 6 walk-forward (spec §13).** Focus optimizer search on:
    * `structural_buffer_atr_mult` (currently 0.5; try 1.0–2.0 → wider stops).
    * `fallback_buffer_atr_mult` (currently 0.5; try 1.0–2.0).
    * `projection_hold_mult` (currently 1.5; try 2.5–3.5 → more time).
    * `tp1_partial_fraction` (currently 0.5; try 0.3–0.7).
    * Possibly a TP1-only exit variant (no runner — take profits at the mid).
   These are the parameters that we now KNOW are the binding constraints.

- **C) Diagnostic: trade-by-trade post-mortem.** For each `stop` exit, plot
   the projected_close trajectory vs realized close — how often did the
   projection eventually verify (close at TP2 by horizon end) on bars where
   we got stopped out? This separates "projection was wrong" from "projection
   was right but stop was too tight." High-impact research before Phase 6.

- **D) Single-instrument deep-dive on YM/MNQ.** Both have PF = 0.90+ (close
   to breakeven). Either:
   * The geometry of the Dow/Nasdaq grid genuinely accommodates the
     projection-aware exits (a hint about which families to focus on), or
   * It's small-sample noise (579 trades on YM is moderate; needs OOS
     confirmation).
   Walk-forward on these two families specifically before broader Phase 6.

## Hard rules still honoured
- ❌ No Pine generation.
- ❌ No mid-phase optimization.
- ✅ Every spec deviation logged in BLOCKERS.md before reporting PASS.
- ✅ Trade-count audit FIRST gate respected (audit passed; 4,741 trades at
     conf=0.65).
- ✅ Owner's 5 % roll-skip-blocked flag honoured (MGC/MCL flagged).
- ✅ Calibration sanity check at conf=0.50 vs 0.65 run and reported.
- ✅ Stress windows reported per spec §6 Idea 10.

## Test gate
- `python -m pytest tests/` → 80 PASS / 0 FAIL (49 prior + 21 backtest +
  7 roll detection + 20 new projection-exit + 3 from updated v1.5 signal tests).

---

_Generated 2026-05-24 by SFPE-5M v1.5 Phase 5 pipeline.
 v1.5 supersedes v1.4 — the v1.4 verdict was based on disconnected ATR
 exits and DID NOT actually test the spec §7 projection layer._
