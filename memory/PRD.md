# SFPE-5M — Project PRD

## Product Summary

**SFPE-5M (Synthetic Forward-Projection Trading Engine, 5-Minute Edition)** is a research-grade Python repository that develops, optimizes, and validates futures trading strategies on completed 5-minute OHLCV bars. The system does not rely on conventional indicators. Instead it (in the full vision, across phases 0–8) constructs **synthetic market candles** with four engines and forward-projects the next candle's completion under structural constraints.

**Repo root:** `/app/sfpe_5m/`

**Constraints (per spec):**
- 5-minute OHLCV only — no ticks, order book, quotes, broker, live trading.
- Strictly causal — every rolling/EMA/threshold uses past data only; mandatory `tests/test_no_lookahead.py` truncates input and asserts byte-identical historic output.
- No Pine Script until full walk-forward PASS verdict exists (spec §18 rule #10).

## What v1 Delivers (Built and Verified)

**Phase 0** — Repo scaffold per spec §4, exact YAML configs per spec §3 (instruments, calendars, portfolio), README, BLOCKERS.md.

**Phase 1** — Data audit + integrity + roll detection for 9 instruments:
- `reports/data_integrity_summary.md` (PASS/WARN/FAIL per instrument)
- `reports/data_integrity_by_instrument.csv`
- `reports/roll_candidates.csv` (4,551 close→open gaps > 5×ATR_20 flagged)
- `reports/session_coverage_heatmap.png`

**Phase 2 (priority engines only)** — Two synthetic engines:
- **Engine C (`vol_budget`)** — Parkinson variance accumulator. Verified PASS on all 9 instruments (avg 5.68–6.19 bars/session, |ac₁| ≤ 0.044).
- **Engine A (`dollar_imbalance`)** — Signed-notional accumulator with stopped-random-walk threshold. Verified PASS on all 9 instruments (avg 8.39–9.78 bars/session, |ac₁| ≤ 0.040).
- Engines B + D stubbed with `NotImplementedError`.
- Per-(engine, symbol) markdown diagnostics + histogram PNGs in `reports/engine_diagnostics/`.

**Tests** — 15 pytest tests all green, including spec §11.4 mandatory no-lookahead test on both engines (4,885 bars compared for vol_budget, 6,690 for dollar_imbalance, 0 mismatches each).

## Reproducibility

```bash
cd /app/sfpe_5m
pip install -r requirements.txt

# Verify core mechanics (POC, exit 0 required):
python scripts/test_core.py

# Full audit:
python scripts/run_data_audit.py

# Run priority engines:
python scripts/run_engines.py

# End-to-end pipeline:
python scripts/run_pipeline.py

# Tests:
pytest -q tests/
```

## Future Versions

- **v2**: Phase 2 completion (Engines B volume-time, D range-budget) + Phase 3 features (absorption, VPIN proxy, TPO, liquidity vacuum, regime router, magnitude projection).
- **v3**: Phase 4 — forward projection per-engine + ensemble + confidence.
- **v4**: Phase 5 — event-driven backtest + 10 baselines + 3 cost models + slippage 1x/2x/3x.
- **v5**: Phase 6 — walk-forward (fast protocol 12m/3m/3m/1m) + staged optimization + parameter stability.
- **v6**: Phase 7 — final markdown/HTML report + tear-sheet + PASS/FAIL verdict.
- **v7 (only if v6 PASSes)**: Phase 8 — Pine v6 templates + per-instrument JSON params.
