"""Per-source-bar engine-state traces for the SFPE-5M projection layer.

For each of the 4 engines, we replay the engine's accumulator logic in "trace
mode" and emit one row of in-progress state PER SOURCE BAR.  Strictly causal
by construction.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from sfpe.synthetic.base import parkinson_variance


STATE_COLS = [
    "synth_open_idx", "synth_open_time", "synth_open_price",
    "synth_high_so_far", "synth_low_so_far", "synth_close_so_far",
    "synth_progress", "synth_progress_abs", "synth_target",
    "synth_bars_elapsed", "synth_velocity",
    "synth_will_close", "synth_bias_raw",
]


def _state_to_df(idx, cols_dict, df_index) -> pd.DataFrame:
    out = pd.DataFrame(cols_dict, index=df_index)
    return out


# ============================================================================
# Engine C — Vol-budget trace
# ============================================================================

def vol_budget_trace(
    df: pd.DataFrame,
    *,
    symbol: str,
    target_bars_per_session: int = 18,
    variance_lookback_sessions: int = 20,
    sigma_mult: float = 1.0,
    variance_proxy: str = "parkinson",
    min_source_bars: int = 1,
    max_source_bars: int = 78,
    velocity_window_bars: int = 20,
) -> pd.DataFrame:
    n = len(df)
    if variance_proxy == "parkinson":
        var_arr = np.array(
            [parkinson_variance(h, lo_)
             for h, lo_ in zip(df["high"].values, df["low"].values)],
            dtype=float,
        )
    else:
        lr = df["log_return"].values
        var_arr = np.where(np.isnan(lr), 0.0, lr ** 2)

    df_local = df[["session_date"]].copy()
    df_local["_var"] = var_arr
    sess_var = df_local.groupby("session_date")["_var"].sum().rename("sess_var")
    sess_var_shift = sess_var.shift(1)
    sess_var_mean = sess_var_shift.rolling(
        window=variance_lookback_sessions, min_periods=variance_lookback_sessions
    ).mean()
    target_per_session = (sess_var_mean / target_bars_per_session) * sigma_mult

    vel = (pd.Series(var_arr).shift(1)
           .rolling(window=velocity_window_bars, min_periods=velocity_window_bars)
           .mean()).values

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    sds = df["session_date"].values
    times = df["timestamp"].tolist()

    so_open_idx = -1
    so_open_time = None
    so_open_price = float("nan")
    so_hi = -np.inf
    so_lo = np.inf
    so_var = 0.0
    so_bars = 0

    cols = {c: [] for c in STATE_COLS}

    for t in range(n):
        sd = sds[t]
        sigma2_target = target_per_session.get(sd, np.nan)
        is_session_start = (t == 0) or (sds[t] != sds[t - 1])
        is_session_end = (t == n - 1) or (sds[t + 1] != sd)

        if is_session_start:
            so_open_idx = t
            so_open_time = times[t]
            so_open_price = opens[t]
            so_hi = highs[t]
            so_lo = lows[t]
            so_var = 0.0
            so_bars = 0

        if variance_proxy == "parkinson":
            so_var += parkinson_variance(highs[t], lows[t])
        else:
            so_var += var_arr[t]
        if highs[t] > so_hi:
            so_hi = highs[t]
        if lows[t] < so_lo:
            so_lo = lows[t]
        so_bars += 1

        if pd.isna(sigma2_target) or sigma2_target <= 0:
            will_close = False
        else:
            budget_hit = (so_var >= sigma2_target) and (so_bars >= min_source_bars)
            max_hit = so_bars >= max_source_bars
            will_close = bool(budget_hit or max_hit or is_session_end)

        cols["synth_open_idx"].append(so_open_idx)
        cols["synth_open_time"].append(so_open_time)
        cols["synth_open_price"].append(so_open_price)
        cols["synth_high_so_far"].append(so_hi)
        cols["synth_low_so_far"].append(so_lo)
        cols["synth_close_so_far"].append(closes[t])
        cols["synth_progress"].append(so_var)
        cols["synth_progress_abs"].append(so_var)
        cols["synth_target"].append(sigma2_target)
        cols["synth_bars_elapsed"].append(so_bars)
        cols["synth_velocity"].append(vel[t])
        cols["synth_will_close"].append(will_close)
        cols["synth_bias_raw"].append(
            1 if closes[t] > so_open_price else (-1 if closes[t] < so_open_price else 0)
        )

        if will_close and not is_session_end:
            so_open_idx = t + 1
            so_open_time = times[t + 1]
            so_open_price = opens[t + 1]
            so_hi = highs[t + 1]
            so_lo = lows[t + 1]
            so_var = 0.0
            so_bars = 0

    return _state_to_df(None, cols, df.index)


# ============================================================================
# Engine A — Dollar-imbalance trace
# ============================================================================

def dollar_imbalance_trace(
    df: pd.DataFrame,
    *,
    symbol: str,
    point_value: float,
    imbalance_window: int = 50,
    theta_mult: float = 1.0,
    target_bars_per_session: int = 18,
    expected_bars_per_session: int = 78,
    min_source_bars: int = 1,
    max_source_bars: int = 78,
    velocity_window_bars: int = 10,
    zero_sign_policy: str = "carry_positive",
) -> pd.DataFrame:
    n = len(df)
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    vols = df["volume"].values
    sds = df["session_date"].values
    times = df["timestamp"].tolist()

    signed_src = np.zeros(n, dtype=float)
    for t in range(n):
        same = (t > 0) and (sds[t] == sds[t - 1])
        if same:
            d = closes[t] - closes[t - 1]
            sgn = 1.0 if d > 0 else (-1.0 if d < 0 else
                                     (1.0 if zero_sign_policy == "carry_positive" else -1.0))
        else:
            sgn = 1.0 if closes[t] >= opens[t] else -1.0
        signed_src[t] = sgn * vols[t] * point_value

    abs_signed_s = pd.Series(np.abs(signed_src)).shift(1)
    rolling_mean = abs_signed_s.rolling(window=imbalance_window,
                                        min_periods=imbalance_window).mean()
    scale = math.sqrt(float(expected_bars_per_session)
                      / float(max(target_bars_per_session, 1)))
    theta_series = (theta_mult * rolling_mean * scale).values

    alpha = 2.0 / (velocity_window_bars + 1.0)
    vel = np.full(n, np.nan, dtype=float)
    e = float("nan")
    for t in range(n):
        if t > 0:
            v = abs(signed_src[t - 1])
            if math.isnan(e):
                e = v
            else:
                e = alpha * v + (1.0 - alpha) * e
        vel[t] = e

    so_open_idx = -1
    so_open_time = None
    so_open_price = float("nan")
    so_hi = -np.inf
    so_lo = np.inf
    so_signed = 0.0
    so_bars = 0

    cols = {c: [] for c in STATE_COLS}

    for t in range(n):
        sd = sds[t]
        is_session_start = (t == 0) or (sds[t] != sds[t - 1])
        is_session_end = (t == n - 1) or (sds[t + 1] != sd)

        if is_session_start:
            so_open_idx = t
            so_open_time = times[t]
            so_open_price = opens[t]
            so_hi = highs[t]
            so_lo = lows[t]
            so_signed = 0.0
            so_bars = 0

        so_signed += signed_src[t]
        if highs[t] > so_hi:
            so_hi = highs[t]
        if lows[t] < so_lo:
            so_lo = lows[t]
        so_bars += 1

        theta_t = theta_series[t]
        if not (np.isnan(theta_t)) and theta_t > 0:
            budget_hit = (abs(so_signed) >= theta_t) and (so_bars >= min_source_bars)
        else:
            budget_hit = False
        max_hit = so_bars >= max_source_bars
        will_close = bool(budget_hit or max_hit or is_session_end)

        cols["synth_open_idx"].append(so_open_idx)
        cols["synth_open_time"].append(so_open_time)
        cols["synth_open_price"].append(so_open_price)
        cols["synth_high_so_far"].append(so_hi)
        cols["synth_low_so_far"].append(so_lo)
        cols["synth_close_so_far"].append(closes[t])
        cols["synth_progress"].append(so_signed)
        cols["synth_progress_abs"].append(abs(so_signed))
        cols["synth_target"].append(theta_t)
        cols["synth_bars_elapsed"].append(so_bars)
        cols["synth_velocity"].append(vel[t])
        cols["synth_will_close"].append(will_close)
        cols["synth_bias_raw"].append(
            1 if so_signed > 0 else (-1 if so_signed < 0 else 0)
        )

        if will_close and not is_session_end:
            so_open_idx = t + 1
            so_open_time = times[t + 1]
            so_open_price = opens[t + 1]
            so_hi = highs[t + 1]
            so_lo = lows[t + 1]
            so_signed = 0.0
            so_bars = 0

    return _state_to_df(None, cols, df.index)


# ============================================================================
# Engine B — Volume-time trace
# ============================================================================

def volume_time_trace(
    df: pd.DataFrame,
    *,
    symbol: str,
    target_bars_per_session: int = 18,
    session_volume_lookback: int = 20,
    min_source_bars: int = 1,
    max_source_bars: int = 78,
    velocity_window_bars: int = 20,
) -> pd.DataFrame:
    n = len(df)
    sess_vol = df.groupby("session_date")["volume"].sum()
    sess_vol_shift = sess_vol.shift(1)
    sess_vol_mean = sess_vol_shift.rolling(
        window=session_volume_lookback, min_periods=session_volume_lookback
    ).mean()
    v_target = (sess_vol_mean / target_bars_per_session)

    vel = (df["volume"].shift(1)
           .rolling(window=velocity_window_bars, min_periods=velocity_window_bars)
           .median()).values

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    vols = df["volume"].values
    sds = df["session_date"].values
    times = df["timestamp"].tolist()

    so_open_idx = -1
    so_open_time = None
    so_open_price = float("nan")
    so_hi = -np.inf
    so_lo = np.inf
    so_vol_acc = 0.0
    so_bars = 0

    cols = {c: [] for c in STATE_COLS}

    for t in range(n):
        sd = sds[t]
        is_session_start = (t == 0) or (sds[t] != sds[t - 1])
        is_session_end = (t == n - 1) or (sds[t + 1] != sd)
        vt = v_target.get(sd, np.nan)
        if is_session_start:
            so_open_idx = t
            so_open_time = times[t]
            so_open_price = opens[t]
            so_hi = highs[t]
            so_lo = lows[t]
            so_vol_acc = 0.0
            so_bars = 0

        so_vol_acc += vols[t]
        if highs[t] > so_hi:
            so_hi = highs[t]
        if lows[t] < so_lo:
            so_lo = lows[t]
        so_bars += 1

        if pd.isna(vt) or vt <= 0:
            will_close = bool(is_session_end)
        else:
            budget_hit = (so_vol_acc >= vt) and (so_bars >= min_source_bars)
            max_hit = so_bars >= max_source_bars
            will_close = bool(budget_hit or max_hit or is_session_end)

        cols["synth_open_idx"].append(so_open_idx)
        cols["synth_open_time"].append(so_open_time)
        cols["synth_open_price"].append(so_open_price)
        cols["synth_high_so_far"].append(so_hi)
        cols["synth_low_so_far"].append(so_lo)
        cols["synth_close_so_far"].append(closes[t])
        cols["synth_progress"].append(so_vol_acc)
        cols["synth_progress_abs"].append(so_vol_acc)
        cols["synth_target"].append(vt)
        cols["synth_bars_elapsed"].append(so_bars)
        cols["synth_velocity"].append(vel[t])
        cols["synth_will_close"].append(will_close)
        cols["synth_bias_raw"].append(
            1 if closes[t] > so_open_price else (-1 if closes[t] < so_open_price else 0)
        )

        if will_close and not is_session_end:
            so_open_idx = t + 1
            so_open_time = times[t + 1]
            so_open_price = opens[t + 1]
            so_hi = highs[t + 1]
            so_lo = lows[t + 1]
            so_vol_acc = 0.0
            so_bars = 0

    return _state_to_df(None, cols, df.index)


# ============================================================================
# Engine D — Range-budget trace
# ============================================================================

def range_budget_trace(
    df: pd.DataFrame,
    *,
    symbol: str,
    range_k: float = 1.5,
    min_source_bars: int = 1,
    max_source_bars: int = 78,
    velocity_window_bars: int = 20,
) -> pd.DataFrame:
    n = len(df)
    rng = (df["high"] - df["low"]).shift(1)
    vel = rng.rolling(window=velocity_window_bars, min_periods=velocity_window_bars).median().values

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    atrs = df["atr_20"].values
    sds = df["session_date"].values
    times = df["timestamp"].tolist()

    so_open_idx = -1
    so_open_time = None
    so_open_price = float("nan")
    so_hi = -np.inf
    so_lo = np.inf
    so_bars = 0
    so_atr_at_open = float("nan")

    cols = {c: [] for c in STATE_COLS}

    for t in range(n):
        sd = sds[t]
        is_session_start = (t == 0) or (sds[t] != sds[t - 1])
        is_session_end = (t == n - 1) or (sds[t + 1] != sd)

        if is_session_start:
            so_open_idx = t
            so_open_time = times[t]
            so_open_price = opens[t]
            so_hi = highs[t]
            so_lo = lows[t]
            so_bars = 0
            so_atr_at_open = atrs[t]

        if highs[t] > so_hi:
            so_hi = highs[t]
        if lows[t] < so_lo:
            so_lo = lows[t]
        so_bars += 1
        synth_range = so_hi - so_lo
        threshold = (range_k * so_atr_at_open) if (so_atr_at_open and so_atr_at_open > 0) else float("inf")

        budget_hit = (synth_range >= threshold) and (so_bars >= min_source_bars)
        max_hit = so_bars >= max_source_bars
        will_close = bool(budget_hit or max_hit or is_session_end)

        cols["synth_open_idx"].append(so_open_idx)
        cols["synth_open_time"].append(so_open_time)
        cols["synth_open_price"].append(so_open_price)
        cols["synth_high_so_far"].append(so_hi)
        cols["synth_low_so_far"].append(so_lo)
        cols["synth_close_so_far"].append(closes[t])
        cols["synth_progress"].append(synth_range)
        cols["synth_progress_abs"].append(synth_range)
        cols["synth_target"].append(threshold)
        cols["synth_bars_elapsed"].append(so_bars)
        cols["synth_velocity"].append(vel[t])
        cols["synth_will_close"].append(will_close)
        cols["synth_bias_raw"].append(
            1 if closes[t] > so_open_price else (-1 if closes[t] < so_open_price else 0)
        )

        if will_close and not is_session_end:
            so_open_idx = t + 1
            so_open_time = times[t + 1]
            so_open_price = opens[t + 1]
            so_hi = highs[t + 1]
            so_lo = lows[t + 1]
            so_bars = 0
            so_atr_at_open = atrs[t + 1]

    return _state_to_df(None, cols, df.index)
