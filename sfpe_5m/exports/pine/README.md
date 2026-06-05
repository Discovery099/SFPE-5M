# SFPE-5M  —  Pine v6 Export Bundle

> ## ⚠️ STRATEGY MARKED **A_STOP** IN PHASE 5.5 VALIDATION.
> ## THIS PINE EXPORT IS FOR VISUAL INSPECTION OF THE CONCEPT, NOT FOR LIVE TRADING. NO REAL MONEY.

---

## What this bundle contains

| File | Purpose | Count |
|---|---|---|
| `sfpe_5m_<sym>_strategy.pine` | Per-instrument **strategy** with `strategy.entry/exit`, hardcoded v1.5-final-A_STOP defaults, full SFPE-5M concept rendered | 9 (ES, MES, MNQ, YM, MYM, RTY, M2K, MGC, MCL) |
| `sfpe_5m_<sym>_indicator.pine` | Per-instrument **indicator** (no `strategy.*` calls). Same visualisations as the strategy file — can be overlaid on any chart for inspection without affecting strategy backtest accounting | 9 |
| `sfpe_5m_screener.pine` | Single Pine indicator that polls all 9 instruments via `request.security()` and fires alerts when any of them generates a signal | 1 |
| `README.md` | This file | 1 |
| `PARITY_NOTES.md` | Per-feature Python→Pine implementation matrix with all approximations and divergences | 1 |

All 19 Pine files target **Pine Script v6**.

---

## TL;DR — what the strategy is, what the verdict is

SFPE-5M is a research-grade synthetic-bar forward-projection futures trading concept. The Python pipeline implements 4 synthetic-bar engines, 6 structural features, an ensemble projection layer, and a spec §8.3 trade-management overlay (TP1 partial / TP2 runner / structural stop / time-stop). On 5 years of 5-minute RTH data across 9 CME futures (ES, MES, MNQ, YM, MYM, RTY, M2K, MGC, MCL) the strategy produced:

- **PF = 0.77, net P&L = -$146,257 on $100k starting equity, Sharpe = -1.63**
- Statistically indistinguishable from 10 mandatory baselines in PF
- Phase 5.5 forensic post-mortem showed only **24.2 %** projection durability at 3× horizon, below the **30 %** decision-tree A_STOP floor
- Wider-stop counterfactual (W1) fixed only **1.7 %** of stopped trades — wider stops cannot save the strategy

The Pine port is the owner-authorised faithful visualisation of the concept on TradingView live charts. **It is NOT a re-validation attempt and NOT a path to live trading.**

---

## Symbol mapping (TradingView → internal SFPE id)

| Internal | TradingView symbol | Family | Tick size | Point value | Commission/side (est.) |
|---|---|---|---|---|---|
| ES  | `CME_MINI:ES1!`     | sp500   | 0.25  | $50.00  | $2.50 |
| MES | `CME_MINI:MES1!`    | sp500   | 0.25  | $5.00   | $0.85 |
| MNQ | `CME_MINI:MNQ1!`    | nasdaq  | 0.25  | $2.00   | $0.85 |
| YM  | `CBOT_MINI:YM1!`    | dow     | 1.00  | $5.00   | $2.50 |
| MYM | `CBOT_MINI:MYM1!`   | dow     | 1.00  | $0.50   | $0.85 |
| RTY | `CME_MINI:RTY1!`    | russell | 0.10  | $50.00  | $2.50 |
| M2K | `CME_MINI:M2K1!`    | russell | 0.10  | $5.00   | $0.85 |
| MGC | `COMEX_MINI:MGC1!`  | gold    | 0.10  | $10.00  | $1.10 |
| MCL | `NYMEX_MINI:MCL1!`  | oil     | 0.01  | $100.00 | $1.55 |

The `1!` suffix on each TradingView symbol selects the **continuous front-month** contract — same shape as the Python dataset.  Specific contract codes (e.g. `ESZ2025`) will work too but you'll lose the multi-year history for backtesting visualisation.

Commission values are realistic CME 2024 estimates (exchange + clearing + NFA + brokerage); **verify against your own brokerage rate card** before drawing conclusions from the strategy's equity curve in TradingView.

---

## Recommended chart settings

- **Timeframe**: 5-minute (matches the Python research dataset).
- **Session**: Regular trading hours per instrument:
  - Equity index (ES/MES/MNQ/YM/MYM/RTY/M2K): 09:30 – 16:00 America/New_York.
  - Gold (MGC): 08:20 – 13:00 America/New_York.
  - Oil (MCL): 09:00 – 14:30 America/New_York.
  Enable "Regular trading hours" session display in TradingView chart settings.
- **Time zone**: America/New_York (the Pine code computes session/cutoff times in NY time regardless of your chart timezone, but it's clearer to view in NY too).
- **Bar style**: regular candles. The SFPE *synthetic* bars are rendered as forward-projected boxes/lines and should NOT replace the live candles.

---

## Step-by-step TradingView setup

### To run the strategy on ES

1. Open TradingView and switch to the symbol `CME_MINI:ES1!`.
2. Switch to 5-minute timeframe.
3. Pine Editor → New → Strategy script. Paste the contents of `sfpe_5m_es_strategy.pine`.
4. Save → Add to chart.
5. (Optional) Strategy Tester panel → Properties → verify:
   - Initial capital = 100000
   - Order size = 1 contract (the script overrides with risk-based sizing)
   - Commission = $2.50 per contract per side (already set in the script header)
   - Slippage = 1 tick (already set in the script header)
6. Read the dashboard table in the top-right of the chart — it shows every engine's vote, regime, VPIN gate, confidence, and the current open position state.
7. Per the Pine header: **do not be deceived by an in-sample positive equity curve**. The strategy lost 23 % of starting equity over 5 years in the Python research backtest.

### To run the indicator (no strategy backtesting)

Use `sfpe_5m_<sym>_indicator.pine` if you want to see the dashboard, projection zones, synthetic-bar trail, and signal markers WITHOUT TradingView's strategy backtest logic interfering. This is also the recommended file to use for the screener-driven workflow (the strategy file is heavier to render on long histories).

### To run the multi-instrument screener

1. Open TradingView on any 5-minute chart (the chart symbol is irrelevant — the screener pulls each of the 9 SFPE instruments independently).
2. Pine Editor → New → Indicator script. Paste the contents of `sfpe_5m_screener.pine`.
3. Save → Add to chart.
4. "Alerts" tab → Create alert:
   - Condition: "SFPE-5M Screener" → "Any alert() function call"  ← this is the modern way and supports per-symbol message text
   - OR: "Condition: SFPE-5M ANY signal" → fires when any instrument is eligible, single message
   - Frequency: "Once Per Bar Close"
5. The screener dashboard (top-right of the chart) shows per-symbol bias / confidence / eligibility every 5 minutes.

---

## Python feature → Pine implementation matrix

The full matrix with diagnostic detail is in `PARITY_NOTES.md`. Summary:

| Python feature | Pine implementation | Status |
|---|---|---|
| ATR_20 (Wilder) | `ta.atr(20)` | ✅ IDENTICAL |
| Risk-based contract sizing | `floor(risk_dollars / (stop_dist × point_value))` | ✅ IDENTICAL |
| Next-bar-open fill | `barstate.isconfirmed` + Pine v6 fills next bar | ✅ IDENTICAL |
| Conservative same-bar stop-first | Pine v6 default order processing (stop wins over limit on same bar) | ✅ IDENTICAL |
| `math.round_to_mintick` price alignment | `math.round_to_mintick(p)` | ✅ IDENTICAL |
| TP1 partial @ projected_close_mid | `strategy.exit(..., qty_percent=i_partial*100)` | ✅ IDENTICAL semantics |
| TP2 runner @ projected_close_high (long) / projected_close_low (short) | `strategy.exit(..., limit=tp2, stop=eff_stop)` | ✅ IDENTICAL semantics |
| Time-stop = ceil(proj_completion_median × hold_mult) | `bar_index - entry_bar >= max_hold_bars` | ✅ IDENTICAL |
| Session-end flatten at RTH close | `is_session_close_bar` time-of-day match | ✅ IDENTICAL |
| Latest-entry-time cutoff | `pre_cutoff` boolean by ET time | ✅ IDENTICAL |
| Geometric-mean confidence (5 components) | `math.pow(prod, 0.2)` | ✅ IDENTICAL |
| VPIN gate | Rolling 20-bar signed-volume imbalance | 🟡 APPROX (Python uses strict volume-synchronized buckets) |
| 4 synthetic engines | Clock-time accumulators with bias proxies | 🟡 APPROX (Python uses event-time bucketing per engine) |
| Forward-projection envelope | Rolling close mean ± 0.75×stdev | 🟡 APPROX (Python uses per-engine projection + ensemble combination) |
| Regime router | ATR percentile + return autocorrelation | 🟡 APPROX (Python uses a larger feature set with explicit stand_down / stressed_illiquid / ambiguous labels) |
| Absorption / vacuum / TPO overrides | Bar-pattern heuristics (high vol + small body, large body + small retrace, prior-session VAH/VAL) | 🟡 APPROX (Python uses dedicated 6-feature layer) |
| Roll-skip after detected roll | Not implemented in Pine (continuous front-month chart already smooths the rolls) | ➖ OMITTED (immaterial on `1!` continuous tickers) |

Wherever Pine differs from Python, **the Pine output is intended as a visual proxy for the concept** — not a numerical replication. **The Python research verdict (A_STOP) is the authoritative result.**

---

## Known divergences between Python backtest and TradingView strategy tester

1. **VPIN values will differ**. Python uses event-time bucket aggregation; Pine uses a rolling clock-time imbalance proxy. Visual rendering of the gate (PASS / HALF / FAIL) will be qualitatively similar most of the time but quantitatively different on any specific bar.
2. **Synthetic-bar emission frequency** will differ. Python emits a new synthetic bar each time a per-engine threshold is breached; Pine renders a *fixed-horizon* projected trail every signal.  Signal *direction* should agree most of the time; trail *length and shape* are stylised.
3. **Regime labels** in Pine collapse the 5-state Python labelling (`balanced_or_choppy / noise_mean_reverting / momentum_trending / stand_down / stressed_illiquid`, plus `ambiguous`) into the same 5 states but computed from a simpler feature set. Pine will rarely if ever emit `ambiguous` whereas Python emits it frequently in low-information windows.
4. **Structural overrides** in Python use absolute price levels from absorption-detection / vacuum-detection / TPO-target features. Pine uses bar-pattern heuristics that pick up the *same kinds of bars* but the exact stop anchor level may differ by 0–3 ticks.
5. **Roll skip** is OFF in Pine. On TradingView `1!` continuous tickers the futures roll is already stitched smoothly by the data feed, so the Python `roll_skip_idxs` mechanism is unnecessary in Pine (and the Python results showed it blocks <5 % of signals on equities, immaterial impact).
6. **Commission / slippage values** in Pine are realistic 2024 CME estimates baked into each strategy file. If your real brokerage charges differently, edit the `commission_value` parameter on the script's `strategy()` declaration (top of the file, BEFORE you save).

---

## Header comment block (every file)

Every Pine file begins with a header block containing:
- The A_STOP warning and the v1.5-final Phase 5.5 verdict numbers.
- The full list of features that ported *cleanly* (full parity).
- The full list of features that are *approximated*, with a one-line summary of the Pine technique used for each.
- The instrument-specific hardcoded constants (point_value, tick_size, RTH session, commission).
- The hardcoded v1.5-final-A_STOP parameter defaults.

The explicit instruction at the bottom of every header: **"DO NOT MODIFY THESE DEFAULTS TO MAKE THE STRATEGY APPEAR PROFITABLE. THE A_STOP VERDICT IS THE RESEARCH OUTPUT."**

---

## What to do next

1. Load any of the Pine files into TradingView and visually study the strategy's behaviour on live data.
2. Read `PARITY_NOTES.md` to understand exactly where the Pine version diverges from the Python research engine.
3. **DO NOT TRADE WITH REAL MONEY** based on Pine output alone. The Python research found PF = 0.77 over 5 years — a Pine-tester equity curve that disagrees is more likely to reflect TradingView replay quirks (gaps, holidays, missing bars) than a genuine edge.
4. If you want to extend the toolkit for future research hypotheses, see the project root `README.md` “What's reusable” section for the strategy-agnostic Python components.
