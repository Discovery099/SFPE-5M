"""Spec §12 mandatory backtest baselines (10 strategies).

Each baseline produces a per-source-bar DataFrame with at minimum:
  - `bias` (-1 short / 0 abstain / +1 long)
  - `trade_eligible` (bool)  -- if True the EventEngine will consider a fill on bar t+1
  - `regime_label` (str, default "baseline")
  - `vpin_gate` (str, default "allow")
  - `session_phase` (str, default "")
  - `ensemble_confidence` (float, default 0.0; baselines are uniform-conf)

All baselines are STRICTLY CAUSAL -- they only consume source columns visible
at bar t.  Outputs are aligned 1:1 with the source DataFrame.

The 10 baselines are (interpretation per BLOCKERS §40 -- the literal spec
§12 list was not available in this build environment so we picked a standard
futures intraday baseline set):
  1. buy_and_hold_intraday
  2. prior_bar_momentum
  3. prior_bar_mean_reversion
  4. atr_breakout
  5. vwap_mean_reversion
  6. opening_range_breakout
  7. random_entry_matched_holding
  8. ema_crossover_9_21
  9. donchian_channel_20
 10. bollinger_mean_reversion_20
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BASELINE_COLS = ["bias", "trade_eligible", "ensemble_confidence",
                 "regime_label", "vpin_gate", "session_phase"]


def _empty_signal_frame(n: int) -> pd.DataFrame:
    return pd.DataFrame({
        "bias": np.zeros(n, dtype=int),
        "trade_eligible": np.zeros(n, dtype=bool),
        "ensemble_confidence": np.full(n, 0.5, dtype=float),
        "regime_label": np.array(["baseline"] * n, dtype=object),
        "vpin_gate": np.array(["allow"] * n, dtype=object),
        "session_phase": np.array([""] * n, dtype=object),
    })


# ---------------------------------------------------------------------------
# 1. Buy & hold intraday: enter long on the FIRST bar of every session.
# Engine session-end policy will force-flatten at end of session.
# ---------------------------------------------------------------------------
def buy_and_hold_intraday(source_df: pd.DataFrame) -> pd.DataFrame:
    n = len(source_df)
    out = _empty_signal_frame(n)
    if "is_first_bar_of_session" in source_df.columns:
        mask = source_df["is_first_bar_of_session"].values.astype(bool)
    else:
        sd = source_df["session_date"].values
        mask = np.r_[True, sd[1:] != sd[:-1]]
    out.loc[mask, "bias"] = 1
    out.loc[mask, "trade_eligible"] = True
    return out


# ---------------------------------------------------------------------------
# 2. Prior-bar momentum: if prior bar closed up vs its open, go long; else short.
# ---------------------------------------------------------------------------
def prior_bar_momentum(source_df: pd.DataFrame) -> pd.DataFrame:
    n = len(source_df)
    out = _empty_signal_frame(n)
    same_sess = source_df["session_date"] == source_df["session_date"].shift(1)
    prev_close = source_df["close"].shift(1)
    prev_open = source_df["open"].shift(1)
    up = (prev_close > prev_open) & same_sess
    dn = (prev_close < prev_open) & same_sess
    out.loc[up.values, "bias"] = 1
    out.loc[dn.values, "bias"] = -1
    out.loc[(up | dn).values, "trade_eligible"] = True
    return out


# ---------------------------------------------------------------------------
# 3. Prior-bar mean reversion: opposite of momentum.
# ---------------------------------------------------------------------------
def prior_bar_mean_reversion(source_df: pd.DataFrame) -> pd.DataFrame:
    mo = prior_bar_momentum(source_df)
    mo["bias"] = -mo["bias"]
    return mo


# ---------------------------------------------------------------------------
# 4. ATR breakout: long if close > rolling max(close, K) of prior K bars; short
# if close < rolling min(close, K). Use K = 20 source bars within the session
# (causal: only uses bars strictly before t).
# ---------------------------------------------------------------------------
def atr_breakout(source_df: pd.DataFrame, *, k: int = 20) -> pd.DataFrame:
    n = len(source_df)
    out = _empty_signal_frame(n)
    # Rolling max/min over the prior K bars (shifted by 1 -> strictly causal).
    grp = source_df.groupby("session_date")["close"]
    roll_max = grp.transform(lambda s: s.shift(1).rolling(k, min_periods=k).max())
    roll_min = grp.transform(lambda s: s.shift(1).rolling(k, min_periods=k).min())
    c = source_df["close"]
    up = c > roll_max
    dn = c < roll_min
    out.loc[up.values, "bias"] = 1
    out.loc[dn.values, "bias"] = -1
    out.loc[(up | dn).values, "trade_eligible"] = True
    return out


# ---------------------------------------------------------------------------
# 5. VWAP mean reversion: short if close > VWAP + 1*ATR, long if close < VWAP
# - 1*ATR. VWAP is session-cumulative volume-weighted average price (causal).
# ---------------------------------------------------------------------------
def vwap_mean_reversion(source_df: pd.DataFrame, *, atr_mult: float = 1.0) -> pd.DataFrame:
    n = len(source_df)
    out = _empty_signal_frame(n)
    tp = (source_df["high"] + source_df["low"] + source_df["close"]) / 3.0
    tpv = tp * source_df["volume"]
    by_sess = source_df.groupby("session_date")
    cum_tpv = by_sess["volume"].transform(lambda s: tpv.loc[s.index].cumsum()) if False else None
    # simpler: cumulative-sum tpv & vol per session
    cum_tpv = (tpv.groupby(source_df["session_date"]).cumsum())
    cum_vol = (source_df["volume"].groupby(source_df["session_date"]).cumsum())
    vwap = cum_tpv / cum_vol.replace(0, np.nan)
    # Shift by 1 -> strictly causal (don't use current bar's tpv contribution).
    vwap = vwap.groupby(source_df["session_date"]).shift(1)
    atr = source_df["atr_20"]
    up = source_df["close"] < (vwap - atr_mult * atr)
    dn = source_df["close"] > (vwap + atr_mult * atr)
    out.loc[up.values, "bias"] = 1     # below vwap = long (mean-revert up)
    out.loc[dn.values, "bias"] = -1
    out.loc[(up | dn).values, "trade_eligible"] = True
    return out


# ---------------------------------------------------------------------------
# 6. Opening-range breakout: first 6 bars (30 min on 5-min) define the OR. After
# bar 6, long if close > OR_high, short if close < OR_low. One signal per session.
# ---------------------------------------------------------------------------
def opening_range_breakout(source_df: pd.DataFrame, *, or_bars: int = 6) -> pd.DataFrame:
    n = len(source_df)
    out = _empty_signal_frame(n)
    bi = source_df["bar_index_in_session"] if "bar_index_in_session" in source_df else \
         source_df.groupby("session_date").cumcount()
    by_sess = source_df.groupby("session_date")
    # OR_high/low = high/low over the first `or_bars` of each session, broadcast
    or_high = by_sess["high"].transform(
        lambda s: s.iloc[:or_bars].max() if len(s) >= or_bars else np.nan)
    or_low = by_sess["low"].transform(
        lambda s: s.iloc[:or_bars].min() if len(s) >= or_bars else np.nan)
    after_or = bi >= or_bars
    c = source_df["close"]
    up = (c > or_high) & after_or
    dn = (c < or_low) & after_or
    out.loc[up.values, "bias"] = 1
    out.loc[dn.values, "bias"] = -1
    out.loc[(up | dn).values, "trade_eligible"] = True
    return out


# ---------------------------------------------------------------------------
# 7. Random entry matched holding: seed-fixed coin-flip per session, held until
# session end (engine's session-end flatten handles exit). Provides a fair
# benchmark for "any entry signal beats coin flip?".
# ---------------------------------------------------------------------------
def random_entry_matched_holding(source_df: pd.DataFrame, *,
                                  seed: int = 12345,
                                  entries_per_session: int = 1) -> pd.DataFrame:
    n = len(source_df)
    out = _empty_signal_frame(n)
    rng = np.random.default_rng(seed)
    sessions = source_df["session_date"].drop_duplicates().reset_index(drop=True)
    sess_to_first_idx = source_df.groupby("session_date").indices  # dict[sd]->np.array of row idxs
    for sd in sessions:
        idxs = sess_to_first_idx[sd]
        if len(idxs) < entries_per_session:
            continue
        choose = rng.choice(idxs, size=entries_per_session, replace=False)
        for ci in choose:
            out.iat[int(ci), out.columns.get_loc("bias")] = int(rng.choice([-1, 1]))
            out.iat[int(ci), out.columns.get_loc("trade_eligible")] = True
    return out


# ---------------------------------------------------------------------------
# 8. EMA crossover 9/21 (causal): long when EMA9 > EMA21, short when EMA9 < EMA21.
# Session-aware: EMAs reset at session open.
# ---------------------------------------------------------------------------
def _session_aware_ema(values: pd.Series, session_id: pd.Series, span: int) -> pd.Series:
    alpha = 2.0 / (span + 1.0)
    out = np.full(len(values), np.nan, dtype=float)
    prev_sid = None
    ema = float("nan")
    vals = values.values
    sids = session_id.values
    for i in range(len(vals)):
        if sids[i] != prev_sid:
            ema = float(vals[i])
            prev_sid = sids[i]
        else:
            ema = alpha * float(vals[i]) + (1.0 - alpha) * ema
        out[i] = ema
    return pd.Series(out, index=values.index)


def ema_crossover_9_21(source_df: pd.DataFrame, *,
                       fast: int = 9, slow: int = 21) -> pd.DataFrame:
    n = len(source_df)
    out = _empty_signal_frame(n)
    ef = _session_aware_ema(source_df["close"], source_df["session_date"], fast)
    es = _session_aware_ema(source_df["close"], source_df["session_date"], slow)
    # Compare prior-bar EMAs to current-bar EMAs to detect crossovers, BUT for
    # a simple state-based signal we just compare current EMA values.
    up = ef > es
    dn = ef < es
    # Strictly causal: shift the comparison by 1 bar (use prior-bar EMA values).
    up_c = up.shift(1).fillna(False).astype(bool)
    dn_c = dn.shift(1).fillna(False).astype(bool)
    out.loc[up_c.values, "bias"] = 1
    out.loc[dn_c.values, "bias"] = -1
    out.loc[(up_c | dn_c).values, "trade_eligible"] = True
    return out


# ---------------------------------------------------------------------------
# 9. Donchian channel 20-bar breakout: long if close > rolling_max(high, 20),
# short if close < rolling_min(low, 20). Causal (shifted).
# ---------------------------------------------------------------------------
def donchian_channel_20(source_df: pd.DataFrame, *, k: int = 20) -> pd.DataFrame:
    n = len(source_df)
    out = _empty_signal_frame(n)
    grp_hi = source_df.groupby("session_date")["high"]
    grp_lo = source_df.groupby("session_date")["low"]
    hi = grp_hi.transform(lambda s: s.shift(1).rolling(k, min_periods=k).max())
    lo = grp_lo.transform(lambda s: s.shift(1).rolling(k, min_periods=k).min())
    c = source_df["close"]
    up = c > hi
    dn = c < lo
    out.loc[up.values, "bias"] = 1
    out.loc[dn.values, "bias"] = -1
    out.loc[(up | dn).values, "trade_eligible"] = True
    return out


# ---------------------------------------------------------------------------
# 10. Bollinger band mean reversion (20-bar, 2.0 sigma): long if close < BB_low,
# short if close > BB_high.  Causal session-aware rolling stats.
# ---------------------------------------------------------------------------
def bollinger_mean_reversion_20(source_df: pd.DataFrame, *,
                                  k: int = 20, n_sigma: float = 2.0) -> pd.DataFrame:
    n = len(source_df)
    out = _empty_signal_frame(n)
    grp = source_df.groupby("session_date")["close"]
    m = grp.transform(lambda s: s.shift(1).rolling(k, min_periods=k).mean())
    sd = grp.transform(lambda s: s.shift(1).rolling(k, min_periods=k).std(ddof=0))
    upper = m + n_sigma * sd
    lower = m - n_sigma * sd
    c = source_df["close"]
    up = c < lower      # below lower band -> mean-revert up = long
    dn = c > upper      # above upper band -> mean-revert down = short
    out.loc[up.values, "bias"] = 1
    out.loc[dn.values, "bias"] = -1
    out.loc[(up | dn).values, "trade_eligible"] = True
    return out


BASELINES: dict = {
    "buy_and_hold_intraday":         buy_and_hold_intraday,
    "prior_bar_momentum":            prior_bar_momentum,
    "prior_bar_mean_reversion":      prior_bar_mean_reversion,
    "atr_breakout":                  atr_breakout,
    "vwap_mean_reversion":           vwap_mean_reversion,
    "opening_range_breakout":        opening_range_breakout,
    "random_entry_matched_holding":  random_entry_matched_holding,
    "ema_crossover_9_21":            ema_crossover_9_21,
    "donchian_channel_20":           donchian_channel_20,
    "bollinger_mean_reversion_20":   bollinger_mean_reversion_20,
}
