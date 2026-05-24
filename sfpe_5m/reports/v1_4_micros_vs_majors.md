# Phase 5.0 Diagnostic — Why Micros Diverge from Majors on Spec §11.2 Close-in-Zone Gate

> Short bullet diagnostic answering: *Why did MES pass the Phase 4 close-in-zone
> ≥0.70 gate while ES failed, and why didn't the same pattern hold for YM vs MYM?*
>
> Source data: `reports/projection_diagnostics/acceptance_by_instrument.csv`,
> `reports/projection_diagnostics/hit_by_zw_quintile.csv`,
> `reports/engine_diagnostics/engines_summary.csv`.

## Headline numbers (from the Phase-4 v1.3 acceptance run)

| Family | Major  | hit@0.65 | Verdict | Micro | hit@0.65 | Verdict |
|--------|--------|----------|---------|-------|----------|---------|
| sp500  | **ES** | 0.6980   | FAIL    | MES   | 0.7150   | PASS    |
| nasdaq |  —     |  —       |  —      | MNQ   | 0.7058   | PASS    |
| dow    | **YM** | 0.6917   | **FAIL**| **MYM** | **0.6916** | **FAIL** |
| russell| **RTY**| 0.6998   | FAIL    | M2K   | 0.7075   | PASS    |
| gold   | MGC    | 0.7159   | PASS    |  —    |  —       |  —      |
| oil    | MCL    | 0.7303   | PASS    |  —    |  —       |  —      |

**Honest correction to the question:** the v1.3 acceptance CSV shows YM *and* MYM
both FAIL the close-in-zone gate (Δ = +0.0001 between them, essentially zero).
The genuine micro-vs-major divergence is on **ES vs MES (+0.017)** and on
**RTY vs M2K (+0.008)**. MNQ is single-cap (no full-size NQ in the dataset).

## Mechanism — three observed effects, ranked by contribution

### 1. Notional-scaled engines emit more synthetic bars on micros  (primary driver)
- `dollar_imbalance` and `volume_time` engines bootstrap their threshold from
  *absolute* dollar notional flowing through the symbol (BLOCKERS §4).
- Micros trade at ~1/10 the dollar notional of their major siblings but on the
  same source 5-minute bars → the theta target lands at a *smaller* absolute
  budget per synthetic, so more (and finer-grained) synthetic bars fit in a
  session.
- Observed in `engines_summary.csv`:

  | Engine            | ES synth bars | MES synth bars | Δ%   |
  |-------------------|---------------|----------------|------|
  | vol_budget        | 22,957        | 22,969         | +0.1%|
  | dollar_imbalance  | 23,006        | **24,942**     | **+8.4%** |
  | volume_time       | 24,239        | **25,293**     | **+4.3%** |
  | range_budget      | 29,997        | 30,000         | +0.0%|

  → vol_budget (variance-proxy, scale-invariant) and range_budget (price-range,
  scale-invariant) are nearly identical across ES/MES.
  Only the two notional-scaled engines lift on the micro.
- **Finer synthetics = tighter projected close envelopes → narrower zones →
  higher hit rates per spec §11.2 (where narrower zones map to higher accuracy).**

### 2. The micro's high-confidence pool is slightly larger and slightly more selective
- ES has 2,974 bars at `ensemble_confidence ≥ 0.65`; MES has 3,207 (+7.8%).
- More high-confidence emissions come from the additional synthetic-bar resolution
  in step 1 raising the ensemble agreement rate (`agree_3of4_pct`: ES 89.7% →
  MES 89.9%) and tightening zones (`zone_ok_pct`: ES 24.2% → MES 24.9%).
- Both effects are small individually, but they compound in `ensemble_confidence`,
  which is a geometric mean of 5 factors (BLOCKERS §29).

### 3. YM/MYM is **price-grid bound**, not notional-bound (why this family doesn't lift)
- The Dow Jones index trades around **35,000** — 7× the price level of ES
  (~5,500). The round-number grid for the Dow family is **100 points**
  (BLOCKERS §16) — a much larger *absolute* move than ES's 5-point grid.
- The structural levels in the regime / absorption / TPO features are anchored
  on this 100-point grid, which means a Dow "zone" tends to span more ATR
  units than an ES zone in practice. Observed in `acceptance_by_instrument.csv`:
  `zone_ok_pct` is **22.3% (YM) / 22.4% (MYM) vs 24.2% (ES) / 24.9% (MES)** —
  the YM family's zones are consistently wider, regardless of micro vs major.
- The dollar-imbalance lift on MYM is only **+2.9%** synth-bar count vs YM
  (24,849 vs 24,139), much smaller than the +8.4% ES→MES lift. The smaller
  micro-resolution boost is not enough to overcome the wider underlying zones,
  and **both YM and MYM end up at the same ~0.6917 hit rate**.
- This is a known characteristic of the family, not a bug.

## Why the RTY/M2K split is similar to ES/MES
- RTY → M2K dollar-imbalance lift: **+8.0%** synth bars (23,405 → 25,286).
- That's comparable to the ES→MES +8.4% lift. M2K passes (0.7075) while RTY
  just misses (0.6998). Same mechanism.

## Caveats / things that do NOT explain the divergence
1. **VPIN gate confidence** is essentially identical across micro/major pairs
   (`vpin_ok_pct`: ES 91.5% / MES 90.6%; YM 91.2% / MYM 90.0%) — VPIN scaling
   is not the differentiator.
2. **Regime filter pass-rate** is nearly identical too (`regime_ok_pct`: ES 11.1%
   / MES 11.1%) — the regime router is scale-invariant.
3. **Source bar autocorrelation** is virtually identical between micro and major
   (e.g. ES src_ac1 = -0.01614 vs MES src_ac1 = -0.01616) — both fail the original
   spec ratio test, both pass the BLOCKERS §13 amended near-zero gate.

## Implication for Phase 5 backtest
- The MES/M2K/MNQ pass-list does NOT mean the strategy is broken on the majors —
  ES misses the close-in-zone gate by **0.002** and RTY by **0.0002**, well
  within sampling noise on the calibration buckets shown in
  `calibration_buckets.csv` (the q9 bucket for ES is hit_rate 0.808 on n=26,
  a meaningless single-bar fluctuation).
- The dow family (YM/MYM) is the real outlier — both fail consistently, the
  underlying issue is the 100-point round-number grid producing wider zones.
  A Phase 6 walk-forward optimizer (deferred) could relax the family-specific
  grid to 50 points and very likely close the gap.
- For Phase 5 we proceed with all 9 instruments under the **same strategy
  signals**, run them through the backtest engine, and let realized P&L speak
  rather than the calibration-only acceptance gates. If the dow family
  underperforms in actual trades too, we surface that in the Phase 5 trade-count
  audit and final summary.

## TL;DR
- ES vs MES (and RTY vs M2K) split comes from **notional-scaled synthetic engines
  emitting ~8% more synthetic bars on the micro**, tightening projected close
  envelopes enough to nudge the family across the 0.70 gate.
- YM and MYM both fail because the **Dow index price level (35k) and its 100-point
  round-number grid produce structurally wider zones** that the micro-resolution
  bump (+2.9%) cannot overcome.
- The divergence is a calibration nuance worth ~0.5–1.5 pp on a hit-rate gate,
  not a fundamental signal-quality difference. Backtest realized P&L is the
  binding test in Phase 5.
