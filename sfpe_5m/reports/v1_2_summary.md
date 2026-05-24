# SFPE-5M — v1.2 (Phase 3) Pipeline Summary

_v1.2 adds the six §6 features (ideas 5–10) on top of the v1.1 engine layer.  Causal gates and per-family bands carried forward unchanged._

## Phase 3 — Feature layer

All 6 features per spec §6 ideas 5–10 are implemented and tested:

| # | Module path                                  | Spec idea | Status |
|---|----------------------------------------------|-----------|--------|
| 5 | `src/sfpe/features/absorption.py`            | Idea 5    | PASS   |
| 6 | `src/sfpe/features/vpin_proxy.py`            | Idea 6    | PASS — bar-accumulation enforced (no intra-bar splitting; docstring + BLOCKERS §21 quote) |
| 7 | `src/sfpe/features/tpo_profile.py`           | Idea 7    | PASS — partial-period merge (<3 bars), POC tie-break = closest to session VWAP (BLOCKERS §22–§23) |
| 8 | `src/sfpe/features/liquidity_vacuum.py`      | Idea 8    | PASS — causal `vacuum_flag` + post-hoc `realized_classification` separated (BLOCKERS §27) |
| 9 | `src/sfpe/features/regime_router.py`         | Idea 9    | PASS — session-aware rolling + overlapping VR (BLOCKERS §19) |
| 10 | `src/sfpe/features/magnitude_projection.py` | Idea 10   | PASS — pooling hierarchy + `state_confidence` + causal terciles (BLOCKERS §24–§25) |

## Test count

**35 / 35 pytest tests pass:**
- 6 feature schema tests (one per feature)
- 6 feature no-lookahead tests (spec §11.4-style — see §11.4 in spec)
- 4 engine no-lookahead tests (carried from v1.1)
- 8 engine quality-gate tests (carried from v1.1)
- 11 misc (loader, integrity, pine-blocked, autocorr gate logic, family classifier, etc.)

Total no-lookahead causal coverage: **10 tests** (4 engines + 6 features), each running on full ES (~122k bars) vs midpoint-truncated ES and asserting byte-identical historic output. Zero mismatches.

## Engine spot-check (per Phase-3 deliverable request)

Beyond ES + MGC verified in v1.1, the additional pair MNQ (equity / nasdaq family) + MCL (commodity / oil family) confirms the 36/36 PASS across all instrument families:

| Symbol | Engine            | Asset class | Band      | Avg bars/sess | Synth ac1   | Verdict |
|--------|-------------------|-------------|-----------|---------------|-------------|---------|
| MNQ    | vol_budget        | equity      | [12, 25]  | 14.67         | +0.0050     | PASS    |
| MNQ    | dollar_imbalance  | equity      | [12, 25]  | 15.80         | +0.0333     | PASS    |
| MNQ    | volume_time       | equity      | [12, 25]  | 16.23         | −0.0042     | PASS    |
| MNQ    | range_budget      | equity      | [12, 25]  | 17.38         | +0.0012     | PASS    |
| MCL    | vol_budget        | commodity   | [10, 20]  | 11.57         | −0.0013     | PASS    |
| MCL    | dollar_imbalance  | commodity   | [10, 20]  | 12.63         | +0.0201     | PASS    |
| MCL    | volume_time       | commodity   | [10, 20]  | 12.56         | −0.0019     | PASS    |
| MCL    | range_budget      | commodity   | [10, 20]  | 15.61         | −0.0019     | PASS    |

(See `reports/engine_diagnostics/engines_summary.csv` for the full 9 × 4 = 36 table.)

## Feature flag rates (sanity, all 9 instruments)

| Feature              | Range across 9 instruments  | Type of event |
|----------------------|------------------------------|---------------|
| absorption_flag      | 0.07–0.49% of source bars    | rare structural |
| vacuum_flag          | 0.28–1.08% of source bars    | rare structural |
| regime non-stand_down| 8.11–11.21%                  | macro state    |
| vpin gate=stand_down | 8.52–12.10%                  | toxicity gate  |
| tpo failed_auction   | 34.42–42.95%                 | broadcast-from-prior-session flag (high by construction) |
| mag_proj state-hit   | 99.78–99.87% of synth bars   | very high coverage |

## Pooling-level distribution (magnitude_projection on ES, vol_budget)

| pooling_level | count   | what it means |
|---------------|---------|---------------|
| 0 (exact)     | 18,834  | exact (engine, regime, vpin, vol, volume, flag, session_phase) match has ≥30 prior samples |
| 1             | 1,580   | dropped `session_phase`, still got ≥30 samples |
| 2             | 1,186   | dropped flag_state |
| 3             | 806     | dropped volume_pct |
| 4             | 335     | dropped vol_pct |
| 5             | 126     | dropped vpin_bucket |
| 6             | 60      | dropped regime; pooled only by engine |
| -1 (NaN)      | 30      | not enough samples even with full pooling → quantiles NaN, state_confidence=0 |

## Deferred / not yet done

- Roll-detection multiplier + calendar gate + volume-signature upgrade (per BLOCKERS §9, pre-Phase-5).
- Phase 4 (forward projection per-engine + ensemble + confidence).
- Phase 5 (backtest + cost models + slippage).
- Phase 6 (walk-forward fast protocol 12/3/3/1).
- Phase 7 (final report + verdict).
- Phase 8 Pine Script (only after Phase 7 PASS).

## Reproducibility

```bash
cd /app/sfpe_5m
pytest -q tests/                                       # 35 passed
python scripts/run_pipeline.py                         # data audit + 4 engines × 9 instruments
python scripts/run_features.py                         # 6 features × 9 instruments + magnitude on vol_budget
```

Feature outputs land in `features/` (per-feature CSVs).  Magnitude projection lands as `features/magnitude_projection__<engine>__<symbol>.csv` per (engine, symbol). Diagnostic summary: `reports/feature_diagnostics/features_summary.{csv,md}`.

## v1.2 verdict

✅ **PASS** — Phase 3 acceptance criteria satisfied:
- All 6 feature modules emit the exact spec §6 field sets
- 10/10 no-lookahead tests pass (4 engines + 6 features)
- MNQ + MCL engine spot-check confirms 36/36 from v1.1
- Every Phase-3 default has a BLOCKERS.md entry (§§16–28)
- Lint clean
