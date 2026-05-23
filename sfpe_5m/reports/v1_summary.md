# SFPE-5M  —  v1.1 Pipeline Summary

_v1.1 applies Spec Amendments 1 (autocorrelation gate) and 2 (per-family bands per §11.1). See BLOCKERS.md §12–§15._

## Phase 1 — Data audit

Instruments processed: **9**  
PASS: **8**  
WARN: **1**  
FAIL: **0**

See `reports/data_integrity_summary.md` for the full table.

> **Note (deferred):** the `roll_candidates.csv` count is currently over-flagged (~4,551). The detector multiplier + calendar + volume-signature upgrade is documented in `BLOCKERS.md §9` and will land before the Phase 5 backtest cycle.

## Phase 2 — All four synthetic engines (v1.1)

Engine runs: **36** (4 engines × 9 instruments)  
Gate PASS: **36**  
Gate FAIL: **0**

See `reports/engine_diagnostics/` for per-(engine, symbol) diagnostics (asset class + per-family band displayed, source & synthetic lag-1 autocorr displayed, autocorr-gate reason quoted).

## v1.1 verdict

✅ **PASS** — Phase 1 audit + Phase 2 all four engines pass the v1.1-corrected §11.1 acceptance gates (per-family band + combined autocorr).

## Deferred to later versions

- Roll-detection multiplier + calendar + volume-signature upgrade (before Phase 5)
- Phase 3 features (absorption, VPIN proxy, TPO, liquidity vacuum, regime router, magnitude projection)
- Phase 4 forward projection + ensemble
- Phase 5 backtest + baselines + cost models
- Phase 6 walk-forward optimization (fast protocol: 12m / 3m / 3m / 1m)
- Phase 7 final reporting + PASS/FAIL verdict
- Phase 8 Pine Script export (only if Phase 7 PASSes)
