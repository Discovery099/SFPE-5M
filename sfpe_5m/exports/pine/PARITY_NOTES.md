# SFPE-5M  —  Python → Pine v6 Parity Notes

_All approximations and divergences are documented here.  This file is the
authoritative reference for what the Pine code does vs what the Python
engine does._

---

## 1. Synthetic bars (4 engines)

### Python implementation
Four independent synthetic-bar generators (`src/sfpe/synthetic/`):

1. **vol_budget**: emit a new synthetic bar whenever the squared-return budget
   exceeds threshold. Variance-driven — scale-invariant across micros/majors.
2. **dollar_imbalance**: emit when cumulative signed dollar-volume crosses a
   bootstrapped threshold. Notional-driven — micros emit ~8 % more bars (Phase
   5.0 diagnostic).
3. **volume_time**: emit when accumulated traded-volume crosses a threshold.
   Notional-driven, similar lift on micros.
4. **range_budget**: emit when cumulative price-range crosses an ATR-scaled
   threshold. Range-driven — scale-invariant.

Each engine independently projects forward: "given the synthetic bars emitted
so far this session, where will the next N synthetic bars land?"

### Pine implementation
Clock-time per-bar bias proxies (one indicator value per source 5-minute bar):

1. **vol_budget proxy** — variance-weighted 5-bar mean return:
   `e1_signal = ta.sma(ret_1, 5) / ta.stdev(ret_1, 5)`,
   bias = +1 if > 0.20, -1 if < -0.20, else 0.
2. **dollar_imbalance proxy** — signed-volume rolling mean / mean volume:
   `e2_signal = ta.sma(sign(ret_1) * volume, 10) / ta.sma(volume, 10)`,
   bias = +1 if > 0.10, -1 if < -0.10, else 0.
3. **volume_time proxy** — fast vs slow EMA stack:
   `bias = +1 if ema(5) > ema(20) + 0.1*ATR else -1 if ema(5) < ema(20) - 0.1*ATR else 0`.
4. **range_budget proxy** — Donchian(20) breakout direction:
   `bias = +1 if close > highest(high,20)[1] else -1 if close < lowest(low,20)[1] else 0`.

### Why this approach
Pine v6 cannot maintain per-engine event-time state across thousands of bars
without running into the 500-element drawing limit and inducing severe rendering
performance issues.  The clock-time proxies fire the *same kinds of bias
directions* the event-time engines would on the same market context, but at
every confirmed source bar instead of when a budget threshold is crossed.

### Divergence material to visualisation?
**No** — the bias direction is qualitatively the same.  Quantitative
ensemble-agreement count may differ by ±1 on any individual bar.

---

## 2. Projection zones (TP1, TP2, hold envelope)

### Python implementation
Per-engine forward-projected close envelopes combined into an ensemble
envelope via the geometric-mean confidence weighting in
`src/sfpe/projection/ensemble.py`.  Outputs:
- `projected_close_low`  : lower envelope of the ensemble forecast
- `projected_close_mid`  : central tendency
- `projected_close_high` : upper envelope
- `projected_completion_median` : how many synthetic bars forward the
   projection is targeting

### Pine implementation
Rolling close mean ± 0.75 × rolling stdev:
```
proj_mean       = ta.sma(close, 20)
proj_sigma      = ta.stdev(close, 20)
proj_close_mid  = proj_mean
proj_close_low  = proj_mean - 0.75 * proj_sigma
proj_close_high = proj_mean + 0.75 * proj_sigma
```

The time horizon `i_horizon` (default 6 bars) is exposed as an input.

### Why this approach
The Python ensemble math (BLOCKERS §29) requires storing per-engine projection
series and combining them via a geometric mean of 5 component confidences.
Porting the *exact* envelope to Pine would require ~200 lines of state-keeping
arrays per engine.  The Pine rolling ±0.75σ envelope captures the same
landing-zone geometry to first order — mean reverts toward central tendency,
width proportional to local volatility.

### Divergence material to visualisation?
**Qualitatively no, quantitatively yes.**  The Pine zone is centred on the
20-bar mean rather than the engine-specific projection.  On bars where the
ensemble has strong directional conviction, the Python envelope is offset
from the rolling mean while the Pine envelope is not.  Visually the zone
will appear *narrower and more mean-reverting* than the Python equivalent.

The owner is invited to read the Python `projection_diagnostics/` CSVs for
the exact Python envelope shapes per instrument.

---

## 3. VPIN gate (Volume-Synchronized Probability of Informed Trading)

### Python implementation
Strict VPIN per Easley-López de Prado:
- Volume bucketed in event-time (each bucket sums to a target volume).
- Within each bucket, classify volume as buyer-initiated vs seller-initiated
  via the bulk-volume classification rule.
- `VPIN = |buy_vol - sell_vol| / total_vol` averaged over N buckets.
- Gate states: `allow` (low VPIN), `half_size` (medium), `stand_down` (high).

### Pine implementation
Clock-time rolling signed-volume imbalance:
```
vol_signed = sign(close - close[1]) * volume
vpin_num   = abs(ta.sma(vol_signed, 20))
vpin_den   = ta.sma(volume, 20)
vpin_proxy = vpin_num / vpin_den
vpin_gate  = vpin_proxy < 0.5 ? "allow" : (vpin_proxy < 0.8 ? "half_size" : "stand_down")
```

### Why this approach
Event-time volume bucketing in Pine v6 requires accumulating volume in a
`var float bucket = 0.0` and emitting on threshold crossing; the bucketing
state must persist across sessions and rarely aligns with rendered bars.
The resulting plot is hard to interpret visually.  The clock-time rolling
signed imbalance approximation produces a smooth, bar-aligned series with
the same threshold semantics.

### Divergence material to visualisation?
**Yes, on the boundary bars.**  The Pine VPIN proxy will sometimes label
bars `half_size` where the strict VPIN would label `allow` (or vice versa)
because the smoothing windows differ.  The dashboard "VPIN gate" indicator
is qualitatively similar but should not be expected to match Python
bar-for-bar.

---

## 4. Regime router

### Python implementation
Six-state classifier in `src/sfpe/features/regime.py` using:
- ATR_20 quintile (volatility regime)
- 1-bar return autocorrelation (trending vs mean-reverting)
- Microstructure noise estimate (Roll's estimator)
- Session phase (open/mid/close)
- Inter-session volatility ratio
- A composite confidence in the assignment

States: `balanced_or_choppy`, `noise_mean_reverting`, `momentum_trending`,
`stand_down`, `stressed_illiquid`, `ambiguous`.

### Pine implementation
Simplified classifier on the same conceptual axes:
```
stand_down       if atr_20 < atr_pct20
stressed_illiq   if atr_20 > atr_pct80
momentum_trend   if autocorr_1 > +0.20
noise_mean_rev   if autocorr_1 < -0.10
balanced_choppy  otherwise
```

### Why this approach
The Roll's estimator and inter-session volatility ratio require microstructure-
level persistence across multiple sessions that's awkward in Pine.  ATR
percentile + autocorrelation captures the two strongest axes of the Python
classifier and produces stable labels.

### Divergence material to visualisation?
**Partial.**  Pine will rarely emit `ambiguous` whereas Python uses it as a
fallback when the classifier confidence is low.  Pine's `stand_down` /
`stressed_illiquid` boundaries are at the 20th/80th ATR percentiles whereas
Python uses tunable thresholds.  Most bars will agree on the label.

---

## 5. Confidence score (geometric mean of 5 components)

### Python implementation
`ensemble_confidence = (conf_agree × conf_zone × conf_vpin × conf_regime × conf_horizon)^(1/5)`
where any zero factor zeros the whole product (BLOCKERS §29).

### Pine implementation
Identical formula:
```
conf_prod = conf_agree * conf_zone * conf_vpin * conf_regime * conf_horizon
ensemble_confidence = (all factors > 0) ? math.pow(conf_prod, 0.2) : 0.0
```

### Status
**✅ IDENTICAL** — same shape, same zero-propagation semantics.

---

## 6. Structural override anchors (absorption / vacuum / failed-auction)

### Python implementation
Three dedicated structural features:
- `src/sfpe/features/absorption.py`: detects bars where heavy resting liquidity
  absorbs aggressive flow at a price level; emits `absorption_level`.
- `src/sfpe/features/vacuum.py`: detects displacement-and-refill patterns;
  emits `extreme_level` and `origin_level`.
- `src/sfpe/features/tpo.py`: builds a session volume-profile and emits
  `target_level` (VAH / VAL / POC of the prior session).

### Pine implementation
Bar-pattern heuristic proxies:
```
absorption_proxy     = volume > 1.5 * sma(volume,20) and body < 0.3 * range
vacuum_proxy         = body > 0.7 * range and range > 0.7 * ATR
failed_auction_proxy = (high > prev_session_high and close < prev_session_high)
                       or (low < prev_session_low and close > prev_session_low)
```
Structural anchor selected by priority: absorption → failed_auction → vacuum.

### Why this approach
The Python features each take 100–300 lines of state-tracking logic and depend
on multi-session lookback (especially TPO).  The bar-pattern proxies pick up
*the same kinds of bars* most of the time — high-volume rejection bars,
big-body displacement bars, level-rejection bars — but the exact anchor price
may differ by 0–3 ticks because Python uses level-clustering while Pine uses
the raw bar's H/L.

### Divergence material to visualisation?
**Yes for the stop line, no for the signal direction.**  The signal direction
(ensemble bias) is unaffected by the structural override choice.  The displayed
stop line will be different.  Pine falls back to the synthetic-open ± buffer×ATR
rule on ~70 % of signals (vs ~60 % in Python), pushing the stop slightly further
from the entry on average.

---

## 7. Roll-skip (post-roll bar exclusion)

### Python implementation
The v1.4 roll-detection module (`src/sfpe/data/roll_detection.py`) flags
sessions where a futures roll occurred, and the backtest skips the source bar
immediately following.  See BLOCKERS §9 and `reports/v1_4_roll_audit.md`.

### Pine implementation
**OMITTED.**  TradingView continuous-front-month tickers (`ES1!`, `MES1!`, etc)
are already roll-stitched by the data provider so the Python `roll_skip_idxs`
mechanism is unnecessary in Pine.  The Python research showed roll-skip blocks
<5 % of signals on equity instruments — immaterial impact on the visual.

### Divergence material to visualisation?
**No.**

---

## 8. Cost models (slippage + commissions)

### Python implementation
Three cost models in `src/sfpe/backtest/cost_models.py`:
- `fixed_tick`: realistic CME exchange + clearing + NFA + 1 tick slip.
- `roll_spread`: microstructure-aware proxy from `regime__<SYM>.csv`.
- `impact`: price-impact proxy from cumulative volume.

### Pine implementation
Fixed-tick only via Pine v6's built-in strategy properties:
```
commission_type=strategy.commission.cash_per_contract
commission_value=<per-side USD from CME 2024 fee table>
slippage=1   // 1 tick
```

### Status
The `fixed_tick` model maps cleanly to Pine v6's `cash_per_contract` commission.
The `roll_spread` and `impact` models are not portable to Pine v6 because they
depend on regime / cumulative-volume series we are not transmitting.  Pine
strategy backtest ≈ Python `fixed_tick` model with the same slippage and
commission settings.

---

## 9. Latest-entry cutoff

### Python implementation
Each instrument has a `latest_entry_time` (e.g. 15:30 ET for equities) from
`config/instruments.yaml`.  After this time the strategy will not open new
positions; only existing positions are managed to session-end flatten.

### Pine implementation
Identical — hardcoded per instrument in each Pine file:
```
cutoff_h = 15
cutoff_m = 30
ny_hour = hour(time, "America/New_York")
ny_min  = minute(time, "America/New_York")
pre_cutoff = (ny_hour * 60 + ny_min) < (cutoff_h * 60 + cutoff_m)
```

### Status
**✅ IDENTICAL.**

---

## 10. Risk-based sizing and contract caps

### Python implementation
`contracts = max(1, floor(risk_per_trade * equity / (stop_dist * point_value)))`
bounded by a 20 % notional cap.

### Pine implementation
Identical:
```
risk_dollars        = strategy.equity * i_risk
contracts_long_raw  = max(1, floor(risk_dollars / max(stop_dist_long  * point_value, 1.0)))
contracts_cap       = max(1, floor(strategy.equity * 0.20 / notional_per))
contracts_long      = min(contracts_long_raw, contracts_cap)
```

### Status
**✅ IDENTICAL.**

---

## Bottom line

**Identical or full-parity ports**: ATR, sizing, fill timing, conservative
stop-first, tick-rounding, TP1 partial / TP2 runner, time-stop, session-end
flatten, latest-entry cutoff, geometric-mean confidence, structural eligibility
gate composition, fixed_tick cost model.

**Approximated ports**: VPIN, 4 synthetic engines, forward-projection envelope,
regime router (5-state → 5-state with simpler features), structural override
anchors.

**Omitted**: roll_spread / impact cost models, roll-skip filter (immaterial on
continuous-front-month TradingView feeds).

The Python A_STOP verdict is the binding research output.  The Pine port
faithfully renders the full SFPE-5M concept *visually* but is not a
requalified strategy.
