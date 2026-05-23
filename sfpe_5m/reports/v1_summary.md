# SFPE-5M  —  v1 Pipeline Summary

## Phase 1 — Data audit

Instruments processed: **9**  
PASS: **8**  
WARN: **1**  
FAIL: **0**

See `reports/data_integrity_summary.md` for the full table.

## Phase 2 — Priority synthetic engines

Engine runs: **18**  
Gate PASS: **18**  
Gate FAIL: **0**

See `reports/engine_diagnostics/` for per-(engine, symbol) diagnostics.

## v1 verdict

✅ **PASS** — Phase 1 + Phase 2 (priority engines) acceptance gates satisfied.

## Deferred to later versions

- Engine B (volume-time) and Engine D (range-budget)
- Phase 3 features (absorption, VPIN proxy, TPO, liquidity vacuum, regime router, magnitude projection)
- Phase 4 forward projection + ensemble
- Phase 5 backtest + baselines + cost models
- Phase 6 walk-forward optimization (fast protocol: 12m / 3m / 3m / 1m)
- Phase 7 final reporting + PASS/FAIL verdict
- Phase 8 Pine Script export (only if Phase 7 PASSes)
