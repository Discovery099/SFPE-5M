"""Spec §5.3 contract-roll discontinuity auto-detector.

We never use externally adjusted prices. Instead we flag candidate rolls whenever
the session-to-session close → open gap exceeds a multiple of the prior session's
ATR_20. The output CSV is informational; downstream strategy/backtest layers can
optionally avoid trading across flagged days.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def detect_rolls(df: pd.DataFrame, *, atr_mult: float = 5.0) -> pd.DataFrame:
    """Flag close[N] → open[N+1] gaps > atr_mult * ATR_20 at session-N close.

    Returns a DataFrame with one row per flagged candidate:
      symbol, date_prev, date_next, close_prev, open_next, gap, gap_atr_mult
    """
    if df.empty:
        return pd.DataFrame(columns=[
            "symbol", "date_prev", "date_next",
            "close_prev", "open_next", "gap", "gap_atr_mult",
        ])

    last = df.groupby("session_date").tail(1).reset_index(drop=True)
    first = df.groupby("session_date").head(1).reset_index(drop=True)

    pair = pd.DataFrame({
        "symbol": last["symbol"],
        "date_prev": last["session_date"],
        "close_prev": last["close"],
        "atr_prev": last["atr_20"],
    })
    pair["date_next"] = first["session_date"].shift(-1).values[:len(pair)]
    pair["open_next"] = first["open"].shift(-1).values[:len(pair)]
    pair = pair.dropna(subset=["date_next", "open_next"]).copy()
    pair["gap"] = (pair["open_next"] - pair["close_prev"]).abs()
    pair["gap_atr_mult"] = pair["gap"] / pair["atr_prev"].replace(0, np.nan)
    flagged = pair[pair["gap_atr_mult"] > atr_mult].copy()
    return flagged.drop(columns=["atr_prev"]).reset_index(drop=True)
