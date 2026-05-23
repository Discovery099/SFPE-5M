"""Spec §5.1 loader. Strictly causal field derivation.

This is the *production* loader used by all scripts. It loads one instrument's
CSV, parses ts_event as UTC-aware, converts to America/New_York, and derives
every causal field listed in spec §5.1.

Guarantees:
  - No future bar is ever read when computing a field at time t.
  - log_return / price_return chains break at session boundaries.
  - true_range at the first bar of a session uses high-low only (no prior close).
  - atr_20 is a session-aware EMA that resets at session start.
  - volume_zscore / range_zscore use a strict left-shifted rolling window so the
    current bar is NOT included in its own normalization stats.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .calendar import Calendar, tag_rth

DERIVED_COLUMNS = [
    "session_date", "bar_index_in_session", "minute_of_session",
    "is_first_bar_of_session", "is_last_bar_of_session",
    "typical_price", "hlc3", "log_return", "price_return",
    "true_range", "atr_20", "volume_zscore", "range_zscore",
]


def load_instrument_csv(
    path: Path,
    calendar: Calendar,
    *,
    atr_span: int = 20,
    zscore_window: int = 500,
    filter_to_rth: bool = True,
) -> pd.DataFrame:
    """Load one instrument CSV with full spec-§5.1 derivations.

    Args:
      path: CSV path.
      calendar: instrument's RTH calendar.
      atr_span: span of the session-aware ATR EMA (default 20 per spec).
      zscore_window: window for volume/range z-scores (default 500 per spec).
      filter_to_rth: if True, drops rows whose timestamp is outside RTH per the
        calendar. The pre-filter count of `out_of_rth_bars` is preserved in
        df.attrs["out_of_rth_bars"] for the integrity report.

    Returns:
      A pandas DataFrame indexed 0..N-1 with the columns listed in DERIVED_COLUMNS
      plus the raw OHLCV and symbol columns.
    """
    raw = pd.read_csv(path)
    if "ts_event" not in raw.columns:
        raise ValueError(f"{path}: missing ts_event column")
    # parse as UTC-aware then convert to America/New_York
    ts = pd.to_datetime(raw["ts_event"], utc=True)
    df = pd.DataFrame({
        "timestamp": ts.dt.tz_convert(calendar.timezone),
        "symbol": raw["symbol"].astype(str),
        "open": raw["open"].astype(float),
        "high": raw["high"].astype(float),
        "low": raw["low"].astype(float),
        "close": raw["close"].astype(float),
        "volume": raw["volume"].astype(float),
    }).sort_values("timestamp").reset_index(drop=True)

    df = tag_rth(df, calendar)
    out_of_rth = int(df["out_of_rth"].sum())
    if filter_to_rth:
        df = df.loc[~df["out_of_rth"]].reset_index(drop=True)
    df = df.drop(columns=["out_of_rth"])

    # session_date = ET calendar date the bar belongs to (within RTH).
    df["session_date"] = df["timestamp"].dt.date

    # bar_index_in_session: 0-based within session
    df["bar_index_in_session"] = df.groupby("session_date").cumcount().astype("int64")

    # minute_of_session: minutes since RTH start
    start_str = f"{calendar.start_et.hour:02d}:{calendar.start_et.minute:02d}:00"
    start_dt = pd.to_datetime(df["session_date"].astype(str) + " " + start_str)
    start_dt = start_dt.dt.tz_localize(calendar.timezone, ambiguous="NaT",
                                       nonexistent="shift_forward")
    df["minute_of_session"] = ((df["timestamp"] - start_dt).dt.total_seconds() // 60).astype("Int64")

    df["is_first_bar_of_session"] = df["bar_index_in_session"] == 0
    next_sd = df["session_date"].shift(-1)
    df["is_last_bar_of_session"] = (next_sd != df["session_date"]) | next_sd.isna()

    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3.0
    df["hlc3"] = df["typical_price"]

    prev_close = df["close"].shift(1)
    same_session = df["session_date"] == df["session_date"].shift(1)
    df["log_return"] = np.where(
        same_session & (prev_close > 0),
        np.log(df["close"] / prev_close),
        np.nan,
    )
    df["price_return"] = np.where(same_session, df["close"] - prev_close, np.nan)

    hl = df["high"] - df["low"]
    hc = (df["high"] - prev_close).abs()
    lc = (df["low"] - prev_close).abs()
    tr_vals = np.where(
        same_session,
        np.maximum.reduce([hl.values, hc.values, lc.values]),
        hl.values,
    )
    df["true_range"] = tr_vals

    df["atr_20"] = _session_aware_ema(df["true_range"], df["session_date"], span=atr_span)

    df["volume_zscore"] = _causal_zscore(df["volume"], window=zscore_window)
    rng = df["high"] - df["low"]
    df["range_zscore"] = _causal_zscore(rng, window=zscore_window)

    df.attrs["out_of_rth_bars"] = out_of_rth
    df.attrs["calendar"] = calendar.name
    df.attrs["expected_bars"] = calendar.expected_bars
    return df


def _session_aware_ema(values: pd.Series, session_id: pd.Series, span: int) -> pd.Series:
    """EMA that resets at every session boundary. Strictly causal."""
    alpha = 2.0 / (span + 1.0)
    out = np.full(len(values), np.nan, dtype=float)
    prev_sid: Optional[object] = None
    ema = float("nan")
    vals = values.values
    sids = session_id.values
    for i in range(len(vals)):
        v = vals[i]
        sid = sids[i]
        if sid != prev_sid:
            ema = float(v) if not (isinstance(v, float) and math.isnan(v)) else float("nan")
            prev_sid = sid
        else:
            if not (isinstance(v, float) and math.isnan(v)):
                if math.isnan(ema):
                    ema = float(v)
                else:
                    ema = alpha * float(v) + (1.0 - alpha) * ema
        out[i] = ema
    return pd.Series(out, index=values.index)


def _causal_zscore(values: pd.Series, window: int) -> pd.Series:
    """Rolling mean+std z-score, with shift(1) so current bar is excluded.

    Returns NaN for the first `window` rows.
    """
    shifted = values.shift(1)
    m = shifted.rolling(window=window, min_periods=window).mean()
    s = shifted.rolling(window=window, min_periods=window).std(ddof=0)
    s = s.replace(0, np.nan)
    return (values - m) / s
