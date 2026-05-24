"""Shared, strictly-causal helpers for the SFPE-5M feature layer (Phase 3).

Everything here is designed to never touch future bars at time t. Each helper
returns NaN during the warmup window so the no-lookahead tests have clean
boundary conditions.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 1) Causal rolling percentile rank
# ---------------------------------------------------------------------------

def causal_percentile_rank(series: pd.Series, window: int) -> pd.Series:
    """Percentile rank of series[t] inside the rolling window [t-window+1 .. t].

    Uses midrank (average of strict-less and less-or-equal counts) to handle ties.
    Returns NaN for the first `window-1` rows.

    Strictly causal: only data up to and INCLUDING bar t enters the calculation
    of the rank at t. Verified by the no-lookahead test suite.
    """
    n = len(series)
    out = np.full(n, np.nan, dtype=float)
    vals = series.values.astype(float)
    for t in range(window - 1, n):
        lo = t - window + 1
        sub = vals[lo:t + 1]
        cur = vals[t]
        less = np.sum(sub < cur)
        leq = np.sum(sub <= cur)
        rank_mid = (less + leq) / 2.0
        out[t] = rank_mid / float(window) * 100.0
    return pd.Series(out, index=series.index)


# ---------------------------------------------------------------------------
# 2) Session VWAP (causal, resets at session start)
# ---------------------------------------------------------------------------

def session_vwap(df: pd.DataFrame) -> pd.Series:
    """Running session VWAP. At each bar t, VWAP uses bars from session_start..t."""
    tp = df["typical_price"].values
    v = df["volume"].values
    sd = df["session_date"].values
    n = len(df)
    out = np.full(n, np.nan, dtype=float)
    cum_pv = 0.0
    cum_v = 0.0
    prev_sd = None
    for t in range(n):
        if sd[t] != prev_sd:
            cum_pv = 0.0
            cum_v = 0.0
            prev_sd = sd[t]
        cum_pv += tp[t] * v[t]
        cum_v += v[t]
        out[t] = (cum_pv / cum_v) if cum_v > 0 else np.nan
    return pd.Series(out, index=df.index)


# ---------------------------------------------------------------------------
# 3) Opening-range high / low (first opening_range_bars of session)
# ---------------------------------------------------------------------------

def opening_range(
    df: pd.DataFrame,
    *,
    opening_range_bars: int = 6,
) -> Tuple[pd.Series, pd.Series]:
    """At each bar t, return (opening_range_high, opening_range_low) for the
    CURRENT session. Both are NaN until the opening range is fully formed.

    Strictly causal: at bar t with bar_index k, OR_high uses bars 0..k for k<6,
    else bars 0..5 of the session.
    """
    or_h = np.full(len(df), np.nan, dtype=float)
    or_l = np.full(len(df), np.nan, dtype=float)
    bidx = df["bar_index_in_session"].values
    highs = df["high"].values
    lows = df["low"].values
    cur_h = -np.inf
    cur_l = np.inf
    locked_h = np.nan
    locked_l = np.nan
    for t in range(len(df)):
        if bidx[t] == 0:
            cur_h = highs[t]
            cur_l = lows[t]
            locked_h = np.nan
            locked_l = np.nan
        else:
            if bidx[t] < opening_range_bars:
                cur_h = max(cur_h, highs[t])
                cur_l = min(cur_l, lows[t])
        if bidx[t] == opening_range_bars - 1:
            locked_h = cur_h
            locked_l = cur_l
        if bidx[t] >= opening_range_bars - 1:
            or_h[t] = locked_h
            or_l[t] = locked_l
    return pd.Series(or_h, index=df.index), pd.Series(or_l, index=df.index)


# ---------------------------------------------------------------------------
# 4) Prior-session levels (high, low, VWAP)
# ---------------------------------------------------------------------------

def prior_session_levels(df: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame indexed like df with columns:
      prior_session_high, prior_session_low, prior_session_vwap, prior_session_close.

    All values are constants within a session and equal to the closing values of
    the immediately preceding session in the same instrument. NaN for the very
    first session in the dataset.
    """
    vwap = session_vwap(df)
    eos = (df.groupby("session_date")
             .apply(lambda g: pd.Series({
                 "high": g["high"].max(),
                 "low": g["low"].min(),
                 "close": g["close"].iloc[-1],
                 "vwap": vwap.loc[g.index].iloc[-1],
             }), include_groups=False))
    eos = eos.shift(1).rename(columns={
        "high": "prior_session_high",
        "low": "prior_session_low",
        "close": "prior_session_close",
        "vwap": "prior_session_vwap",
    })
    return df[["session_date"]].merge(eos, left_on="session_date", right_index=True, how="left")


# ---------------------------------------------------------------------------
# 5) Session phase (open 30m / mid / close 30m)
# ---------------------------------------------------------------------------

def session_phase(
    df: pd.DataFrame,
    *,
    expected_bars: int,
    boundary_bars: int = 6,
) -> pd.Series:
    """Classify each bar into 'open_30m' / 'mid' / 'close_30m'.

    boundary_bars = 6 corresponds to 30 minutes on 5-min bars.
    """
    bidx = df["bar_index_in_session"].astype(int).values
    n = len(df)
    out = np.empty(n, dtype=object)
    # We approximate the session-end boundary using bar_index. Sessions of size
    # `expected_bars` have close-30m bars from (expected_bars - boundary_bars)
    # to expected_bars - 1.
    for t in range(n):
        if bidx[t] < boundary_bars:
            out[t] = "open_30m"
        elif bidx[t] >= expected_bars - boundary_bars:
            out[t] = "close_30m"
        else:
            out[t] = "mid"
    return pd.Series(out, index=df.index)


# ---------------------------------------------------------------------------
# 6) Round-number grid (instrument-aware)
# ---------------------------------------------------------------------------

ROUND_NUMBER_GRID_BY_FAMILY: dict[str, float] = {
    # See BLOCKERS.md §16 for rationale per instrument family.
    "sp500":   5.0,    # ES, MES: every 5 index points
    "nasdaq":  25.0,   # MNQ: every 25 index points (NQ is finer than ES per tick but moves more)
    "dow":     100.0,  # YM, MYM: every 100 index points
    "russell": 5.0,    # RTY, M2K
    "gold":    10.0,   # MGC: every $10
    "oil":     1.0,    # MCL: every $1
}


def nearest_round_number(price: float, grid: float) -> float:
    """Return the round-number-grid level nearest to `price`."""
    return round(price / grid) * grid


# ---------------------------------------------------------------------------
# 7) Within-session returns (causal, NaN at session start)
# ---------------------------------------------------------------------------

def within_session_diff(values: pd.Series, session_id: pd.Series) -> pd.Series:
    """close_t - close_{t-1} within the same session; NaN at session start."""
    prev = values.shift(1)
    same = session_id == session_id.shift(1)
    out = np.where(same, values - prev, np.nan)
    return pd.Series(out, index=values.index)
