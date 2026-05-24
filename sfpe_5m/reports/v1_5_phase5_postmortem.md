# Phase 5.5 Option C — Forensic Post-Mortem (conf=0.65)

_Forensic analysis on the existing v1.5 trade ledger. No new backtest, no parameter tuning, no optimization. Counterfactuals:_
- **W1**: structural_buffer_atr_mult = 1.0 (vs original 0.5), same hold.
- **W2**: structural_buffer_atr_mult = 2.0 AND projection_hold_mult = 3.0 (vs 1.5).
- **Durability**: did price reach TP2 within 3× original max_bars_hold?

## Portfolio (all 9 instruments) — gating numbers

- Stopped trades in the original v1.5 ledger: **2,161**.
- **W1 fixes (wider stop only → TP2): 1.7%**
- W1 still-stops: 64.8%  ;  W1 still-time-stops: 30.8%  ;  W1 session-end: 2.7%
- **W2 fixes (wider + longer → TP2): 7.0%**
- W2 still-stops: 38.9%  ;  W2 still-time-stops: 39.1%  ;  W2 session-end: 14.9%
- **Projection durability (TP2 reached within 3× horizon): 24.2%**
- Zone-visit durability (projected close zone ever touched): 98.8%

## Hypothetical Portfolio P&L (counterfactual exits, original contracts)

_The non-stopped trades keep their original outcome; stopped trades adopt the counterfactual exit. Uses GROSS P&L for the new exits (no slip/cost) for speed — original costs already netted out._

| Scenario | Trades | Net P&L | PF | Win rate |
|---|---|---|---|---|
| original | 4,741 | -161,182 | 0.78 | 41.7% |
| w1 | 4,741 | -162,790 | 0.81 | 46.3% |
| w2 | 4,741 | -174,651 | 0.84 | 52.0% |

## Decision-tree verdict

**A_STOP** — Projection eventual-verification rate is 24.2% < 30% at 3× horizon. The Phase 4 §11.2 close-zone gate is NOT predictive at trade-management timescales. Wider stops cannot save what the projection never delivers. Owner-defined trigger for OPTION A (accept and stop).


## Per-instrument — fix rates and durability

| Symbol | n_stopped | W1 → TP2 | W2 → TP2 | Durability (TP2 in 3×) | Zone visit |
|---|---|---|---|---|---|
| ES | 310 | 3.2% | 7.1% | 17.4% | 99.0% |
| M2K | 270 | 1.9% | 5.9% | 20.4% | 99.3% |
| MCL | 92 | 0.0% | 5.4% | 28.3% | 96.7% |
| MES | 275 | 1.1% | 5.5% | 23.3% | 98.5% |
| MGC | 162 | 0.6% | 6.2% | 40.1% | 99.4% |
| MNQ | 276 | 2.9% | 9.8% | 25.4% | 98.9% |
| MYM | 261 | 0.8% | 6.9% | 24.9% | 98.5% |
| RTY | 259 | 0.8% | 4.6% | 18.1% | 98.5% |
| YM | 256 | 2.0% | 10.5% | 29.7% | 99.6% |

## Family grid-width / ATR ratio (BLOCKERS §16 hypothesis)

| Symbol | family | grid (pts) | median ATR | grid/ATR | TP2 win rate |
|---|---|---|---|---|---|
| ES | sp500 | 5.0 | 5.68 | 0.88 | 6.3% |
| M2K | russell | 5.0 | 3.28 | 1.52 | 6.1% |
| MCL | oil | 1.0 | 0.17 | 5.77 | 7.0% |
| MES | sp500 | 5.0 | 5.81 | 0.86 | 9.1% |
| MGC | gold | 10.0 | 2.42 | 4.14 | 7.3% |
| MNQ | nasdaq | 25.0 | 25.41 | 0.98 | 5.3% |
| MYM | dow | 100.0 | 39.64 | 2.52 | 5.4% |
| RTY | russell | 5.0 | 3.44 | 1.45 | 6.8% |
| YM | dow | 100.0 | 38.34 | 2.61 | 9.3% |

## TP2 winners — feature profile vs full population

| Feature | Value | n_trades | n_winners | Winner rate |
|---|---|---|---|---|
| entry_hour_et | 15 | 767 | 77 | 10.0% |
| entry_hour_et | 14 | 1,175 | 85 | 7.2% |
| entry_hour_et | 12 | 1,303 | 80 | 6.1% |
| entry_hour_et | 13 | 1,264 | 74 | 5.9% |
| entry_hour_et | 11 | 229 | 13 | 5.7% |
| has_structural_override | True | 1,511 | 126 | 8.3% |
| has_structural_override | False | 3,230 | 204 | 6.3% |
| override_kind | failed_auction | 1,484 | 125 | 8.4% |
| override_kind | none | 3,230 | 204 | 6.3% |
| override_kind | vacuum_continuation | 25 | 1 | 4.0% |
| regime_label | noise_mean_reverting | 4,741 | 330 | 7.0% |
| session_phase | close | 660 | 67 | 10.2% |
| session_phase | mid | 4,081 | 263 | 6.4% |
| vpin_gate | half_size | 609 | 44 | 7.2% |
| vpin_gate | allow | 4,132 | 286 | 6.9% |

## Interpretation

- The gating question is: **does the projected close zone get visited / TP2 reached when given more time?**
  - Portfolio durability rate: **24.2%** (TP2 reached in 3× horizon).
  - Portfolio zone-visit rate: **98.8%** (price touched the projected close envelope at any point in 3× horizon).
- If durability is high and W1 fixes most stops, **the projection IS durable and wider stops would convert losers into winners.** Phase 6 is justified.
- If durability is low, the projection only verifies on the 6% TP2-winning trades — the §11.2 close-zone gate is misleading at trade-management timescales. No amount of Phase 6 tuning will save the strategy because the underlying projection is not actionable. Option A is the honest answer.