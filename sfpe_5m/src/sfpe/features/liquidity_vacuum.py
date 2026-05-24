"""Idea 8 - Liquidity Vacuum Detection.

Operates on source 5-minute bars.

Spec §6 Idea 8 (literal):
  vacuum_candidate_t = (
      volume_pct <= low_volume_pct
      AND range_pct >= high_range_pct
      AND displacement_t >= displacement_atr_threshold * atr_20_t
  )

Classification (causal vs post-hoc):
  - At signal time, only `vacuum_flag` is causal.
  - `expected_classification` uses regime + structural levels (see BLOCKERS.md §18).
  - `realized_classification` is a POST-HOC research-only label computed
     `confirmation_bars` ahead; for the most-recent `confirmation_bars` rows of
     the dataset it is NaN. This column MUST NOT be used by any signal at t.

Output fields:
  vacuum_flag, vacuum_side, origin_level, extreme_level,
  expected_snap_back_zone_low, expected_snap_back_zone_high,
  expected_classification, vacuum_confidence,
  realized_classification  (post-hoc, not for signal use)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .common import (
    causal_percentile_rank, prior_session_levels,
    ROUND_NUMBER_GRID_BY_FAMILY, nearest_round_number,
)


@dataclass
class VacuumParams:
    # Defaults: most permissive end of spec §6 search ranges (BLOCKERS.md §20).
    low_volume_pct: float = 30.0
    high_range_pct: float = 70.0
    displacement_atr_threshold: float = 0.75
    confirmation_bars: int = 3
    rolling_window_bars: int = 500
    target_policy: str = "midpoint_retrace"


def compute_vacuum(
    df: pd.DataFrame,
    *,
    family: str,
    params: Optional[VacuumParams] = None,
) -> pd.DataFrame:
    p = params or VacuumParams()
    out = pd.DataFrame(index=df.index)

    displacement = (df["close"] - df["open"]).abs()
    bar_range = df["high"] - df["low"]
    vol_pct = causal_percentile_rank(df["volume"], p.rolling_window_bars)
    rng_pct = causal_percentile_rank(bar_range, p.rolling_window_bars)
    out["displacement"] = displacement
    out["volume_percentile"] = vol_pct
    out["range_percentile"] = rng_pct

    cand = (
        (vol_pct <= p.low_volume_pct)
        & (rng_pct >= p.high_range_pct)
        & (displacement >= p.displacement_atr_threshold * df["atr_20"])
    )
    cand = cand & vol_pct.notna() & rng_pct.notna() & df["atr_20"].notna()
    out["vacuum_flag"] = cand.fillna(False).astype(bool)

    # side: +1 up (close > open) or -1 down
    out["vacuum_side"] = np.where(df["close"] >= df["open"], 1, -1)

    # origin = open of the vacuum bar (set NaN when not flagged)
    # extreme = high if up-side, low if down-side
    origin = np.where(out["vacuum_flag"].values, df["open"].values, np.nan)
    extreme = np.where(out["vacuum_flag"].values,
                       np.where(out["vacuum_side"].values > 0, df["high"].values, df["low"].values),
                       np.nan)
    out["origin_level"] = origin
    out["extreme_level"] = extreme

    # expected snap-back zone
    half_atr = 0.5 * df["atr_20"]
    midpoint = (df["open"] + np.where(out["vacuum_side"].values > 0,
                                       df["high"].values, df["low"].values)) / 2.0
    if p.target_policy == "midpoint_retrace":
        target_low = midpoint - half_atr
        target_high = midpoint + half_atr
    elif p.target_policy == "origin_retest":
        target_low = df["open"] - half_atr
        target_high = df["open"] + half_atr
    else:  # continuation_extension
        target_low = df["close"] - half_atr
        target_high = df["close"] + half_atr
    out["expected_snap_back_zone_low"] = np.where(out["vacuum_flag"].values, target_low, np.nan)
    out["expected_snap_back_zone_high"] = np.where(out["vacuum_flag"].values, target_high, np.nan)

    # expected_classification at signal time:
    #   near round-number break --> continuation;
    #   near prior session high/low (within 0.5*ATR) --> reversal;
    #   else reversal-biased by default for vacuum bars.
    prior = prior_session_levels(df)
    grid = ROUND_NUMBER_GRID_BY_FAMILY.get(family, 5.0)
    closes = df["close"].values
    atrs = df["atr_20"].values
    near_round = np.zeros(len(df), dtype=bool)
    near_prior_extreme = np.zeros(len(df), dtype=bool)
    for t in range(len(df)):
        if not out["vacuum_flag"].values[t]:
            continue
        atr = atrs[t]
        if not np.isfinite(atr) or atr <= 0:
            continue
        rn = nearest_round_number(closes[t], grid)
        if abs(closes[t] - rn) <= 0.3 * atr:
            near_round[t] = True
        ph = prior["prior_session_high"].iloc[t]
        pl = prior["prior_session_low"].iloc[t]
        if (pd.notna(ph) and abs(closes[t] - ph) <= 0.5 * atr) or \
           (pd.notna(pl) and abs(closes[t] - pl) <= 0.5 * atr):
            near_prior_extreme[t] = True
    cls = np.full(len(df), "", dtype=object)
    cls[out["vacuum_flag"].values] = "reversal"  # default
    cls[near_round] = "continuation"
    cls[near_prior_extreme] = "reversal"
    cls[~out["vacuum_flag"].values] = ""
    out["expected_classification"] = cls

    # vacuum_confidence: 1 when flagged + strong structural support, 0 otherwise.
    base = np.where(out["vacuum_flag"].values, 1.0, 0.0)
    boost = np.where(near_round | near_prior_extreme, 1.0, 0.5)
    out["vacuum_confidence"] = base * boost

    # realized_classification (post-hoc).
    # Look `confirmation_bars` ahead at the close vs origin_level; if price has
    # reverted past midpoint -> reversal; if extended past extreme -> continuation;
    # else mixed.
    n = len(df)
    realized = np.full(n, "", dtype=object)
    closes_arr = df["close"].values
    flags = out["vacuum_flag"].values
    origins = origin
    extremes = extreme
    for t in range(n):
        if not flags[t]:
            continue
        end = t + p.confirmation_bars
        if end >= n:
            # future bars unavailable -> leave NaN (empty string here)
            continue
        c_future = closes_arr[end]
        mid = (origins[t] + extremes[t]) / 2.0
        side = out["vacuum_side"].values[t]
        if side > 0:
            if c_future <= mid:
                realized[t] = "reversal"
            elif c_future > extremes[t]:
                realized[t] = "continuation"
            else:
                realized[t] = "mixed"
        else:
            if c_future >= mid:
                realized[t] = "reversal"
            elif c_future < extremes[t]:
                realized[t] = "continuation"
            else:
                realized[t] = "mixed"
    out["realized_classification"] = realized

    return out
