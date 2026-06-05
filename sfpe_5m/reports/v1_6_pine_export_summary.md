# SFPE-5M — v1.6 Pine Export Summary

**Status: Pine v6 export bundle complete. A_STOP verdict preserved.**

---

## Owner-locked scope (BLOCKERS §44, revised 2026-05-24)

- **Phase 6 walk-forward DELIBERATELY NOT EXECUTED.** Owner-revised scope after
  initial Phase 6 authorisation: the v1.5-final-A_STOP parameter set from commit
  `bf427ce` is the canonical research output and is hardcoded as defaults in
  the Pine exports.
- **Pine export is for visual inspection** of the complete SFPE-5M concept on
  TradingView live charts. **Not a re-validation attempt. Not a path to live
  trading.**
- The Phase 5.5 forensic post-mortem A_STOP verdict (durability 24.2 % < 30 %
  decision-tree floor) is **NOT overridden** by Pine export — it stands.

## Files emitted

```
/app/sfpe_5m/exports/pine/
├── README.md                            (10,548 bytes)  — overall bundle README
├── PARITY_NOTES.md                      (10,754 bytes)  — Python ⇄ Pine matrix
├── sfpe_5m_es_strategy.pine             (26,261 bytes)
├── sfpe_5m_es_indicator.pine            (22,164 bytes)
├── sfpe_5m_mes_strategy.pine            ( ~25 KB )
├── sfpe_5m_mes_indicator.pine
├── sfpe_5m_mnq_strategy.pine
├── sfpe_5m_mnq_indicator.pine
├── sfpe_5m_ym_strategy.pine
├── sfpe_5m_ym_indicator.pine
├── sfpe_5m_mym_strategy.pine
├── sfpe_5m_mym_indicator.pine
├── sfpe_5m_rty_strategy.pine
├── sfpe_5m_rty_indicator.pine
├── sfpe_5m_m2k_strategy.pine
├── sfpe_5m_m2k_indicator.pine
├── sfpe_5m_mgc_strategy.pine
├── sfpe_5m_mgc_indicator.pine
├── sfpe_5m_mcl_strategy.pine
├── sfpe_5m_mcl_indicator.pine
└── sfpe_5m_screener.pine                (13,163 bytes)  — cross-symbol alerts
```

**Total: 19 Pine v6 files + 2 docs = 21 deliverables (≈ 420 KB).**

## Generation pipeline

```
src/sfpe/pine_exporter.py        # template generator (615 LOC)
scripts/run_pine_export.py       # driver
tests/test_pine_exporter.py      # 53 tests covering header presence,
                                 # param substitution, Pine v6 patterns,
                                 # walrus-only-on-var bug guard,
                                 # int/float division promotion,
                                 # indicator-vs-strategy mode separation,
                                 # screener request.security coverage
```

To regenerate: `python scripts/run_pine_export.py`.

## Feature parity (full matrix in `exports/pine/PARITY_NOTES.md`)

### ✅ Identical or full parity with Python
- ATR_20 (Wilder) — `ta.atr(20)`
- Risk-based contract sizing — `floor(risk_per_trade × equity / (stop_dist × point_value))`
- Next-bar-open fill — `barstate.isconfirmed`
- Conservative same-bar stop-first — Pine v6 default order processing
- `math.round_to_mintick` for price alignment
- TP1 partial (50 % qty) + TP2 runner via `strategy.exit(..., qty_percent=...)`
- Time-stop = `bar_index − entry_bar ≥ ceil(horizon × hold_mult)`
- Session-end flatten at RTH close (per-instrument: 16:00 / 13:00 / 14:30 ET)
- Latest-entry-time cutoff (15:30 / 13:00 / 14:00 ET per instrument)
- Geometric-mean confidence (5 components, zero-propagation)
- Structural-eligibility gate composition (bias × agreement × VPIN × regime × zone × cutoff)
- Per-instrument fixed_tick cost model (realistic CME 2024 fees)

### 🟡 Approximated (Pine v6 constraints — documented in headers)
- **VPIN gate**: rolling 20-bar signed-volume imbalance proxy (Python uses
  strict volume-synchronized buckets per Easley–López de Prado).
- **4 synthetic engines**: clock-time accumulators with engine-specific bias
  proxies (vol_budget → variance-weighted return, dollar_imbalance → signed
  volume momentum, volume_time → fast/slow EMA crossover, range_budget →
  Donchian breakout). Python uses event-time bucketing per engine.
- **Forward-projection envelope**: rolling close mean ± 0.75 × stdev (Python
  uses per-engine projection + ensemble combination).
- **Regime router**: ATR percentile + return autocorrelation (Python uses
  6-feature classifier including Roll's estimator + inter-session vol).
- **Structural overrides (absorption / vacuum / TPO)**: bar-pattern
  heuristics (Python uses dedicated 100–300 LOC feature modules each).

### ⚪ Omitted (immaterial on TradingView continuous-front-month feeds)
- Roll-skip filter — TradingView `1!` continuous tickers are pre-stitched.
- `roll_spread` and `impact` cost models — depend on Python-side regime /
  cumulative-volume series not transmitted to Pine.

## A_STOP verdict preserved

Every Pine file's header comment block carries:

1. The **A_STOP** warning at the top of the header.
2. The v1.5-final research numbers (PF = 0.77, net = −$146,257 / 5 years /
   $100k starting equity, Sharpe = −1.63).
3. The **NOT FOR LIVE TRADING. NO REAL MONEY.** caveat.
4. The complete approximation matrix.
5. The instruction: **"DO NOT MODIFY THESE DEFAULTS TO MAKE THE STRATEGY
   APPEAR PROFITABLE. THE A_STOP VERDICT IS THE RESEARCH OUTPUT."**

The Phase 5.5 forensic post-mortem and Phase 5 verdict documents
(`reports/v1_5_phase5_VERDICT.md`, `reports/v1_5_phase5_postmortem.md`) are
unchanged. The repository root `README.md` Project Verdict section is
unchanged. The Pine export does not relitigate or revise the A_STOP
verdict in any deliverable.

## Test gate

| Suite | Tests | Status |
|---|---|---|
| `tests/test_data_integrity.py` | 4 | ✅ |
| `tests/test_no_lookahead_*.py` | ~8 | ✅ |
| `tests/test_synthetic_engines.py` | ~12 | ✅ |
| `tests/test_features.py` | 5 | ✅ |
| `tests/test_projection.py` | ~14 | ✅ |
| `tests/test_roll_detection.py` | 7 | ✅ |
| `tests/test_backtest.py` | 21 | ✅ |
| `tests/test_projection_exits.py` | 19 | ✅ |
| **`tests/test_pine_exporter.py`** | **53** | **✅ NEW** |
| **TOTAL** | **143** | **143 PASS in 474s** |

No regressions. All prior tests still green. 53 new tests cover:
- Mandatory header phrases in every Pine file.
- Pine v6 syntax patterns (`//@version=6`, `barstate.isconfirmed`,
  `math.round_to_mintick`, `math.pow`, `ta.atr(20)`,
  `ta.percentile_linear_interpolation`, `hour(time, "America/New_York")`).
- Per-instrument hardcoded constants (point_value, tick_size,
  commission_per_side).
- v1.5-final-A_STOP parameter defaults present in every input.float / input.int.
- Strategy files contain `strategy.entry / strategy.exit`; indicator files
  do NOT (in actual code; the header documents them as "ported features").
- Screener uses `request.security("CME_MINI:ES1!", ...)` etc for all 9
  instruments and emits per-symbol `alert()` calls.
- **No `:=` reassignment on non-`var` identifiers** (would be a Pine syntax
  error — guard against future regression in the template).
- **Int / int division promoted to float** (`h / float(i_horizon)` instead of
  `h / i_horizon`) — guards against the Pine v6 integer-truncation gotcha.

## Next steps

The owner can now:
1. Load any `sfpe_5m_<sym>_strategy.pine` or `sfpe_5m_<sym>_indicator.pine`
   into TradingView's Pine Editor and add it to a chart.
2. Load `sfpe_5m_screener.pine` on any 5-minute chart and configure
   "Any alert() function call" to receive cross-instrument signal alerts.
3. Visually inspect the projection zones, regime labels, VPIN gate,
   per-engine votes, and signal markers on live data.
4. Read `exports/pine/PARITY_NOTES.md` to understand the exact divergences
   between Pine output and the Python research.

**This completes the v1.6 deliverable.** The Phase 5.5 A_STOP verdict remains
the binding research output. The Pine bundle is a faithful visualisation of
the complete SFPE-5M concept on TradingView live data — nothing more.
