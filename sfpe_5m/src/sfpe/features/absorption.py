"""Idea 5 - Absorption Detection via Volume-Displacement Ratio.

Operates on source 5-minute bars. Strictly causal: all percentile ranks use a
rolling left-closed window ending at bar t.

Spec §6 Idea 5 (literal):
  absorption_t = (volume_pct >= absorption_volume_pct
                  AND range_pct <= absorption_range_pct
                  AND body_t <= body_atr_threshold * atr_20_t)

Output fields:
  absorption_flag, absorption_side, anchor_type, absorption_level,
  expected_reversal_zone_low, expected_reversal_zone_high, absorption_confidence

Absorption_side convention (BLOCKERS.md §17):
  - bid_absorption: close near high (buyers absorbed selling pressure)
  - ask_absorption: close near low (sellers absorbed buying pressure)
  - unknown: close near bar midpoint
Near = within close_loc_eps * bar_range from the respective extreme.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .common import (
    causal_percentile_rank, session_vwap, opening_range,
    prior_session_levels, ROUND_NUMBER_GRID_BY_FAMILY, nearest_round_number,
)


@dataclass
class AbsorptionParams:
    # Defaults: most permissive end of spec §6 search ranges (BLOCKERS.md §20).
    absorption_volume_pct: float = 80.0
    absorption_range_pct: float = 30.0
    body_atr_threshold: float = 0.50
    anchor_distance_atr: float = 0.50
    rolling_window_bars: int = 500
    reversal_horizon_bars: int = 6
    close_loc_eps: float = 0.20    # see BLOCKERS.md §17


def compute_absorption(
    df: pd.DataFrame,
    *,
    family: str,
    tick_size: float,
    params: Optional[AbsorptionParams] = None,
) -> pd.DataFrame:
    p = params or AbsorptionParams()
    out = pd.DataFrame(index=df.index)

    bar_range = df["high"] - df["low"]
    body = (df["close"] - df["open"]).abs()
    vol_pct = causal_percentile_rank(df["volume"], p.rolling_window_bars)
    rng_pct = causal_percentile_rank(bar_range, p.rolling_window_bars)
    out["bar_range"] = bar_range
    out["body"] = body
    out["volume_percentile"] = vol_pct
    out["range_percentile"] = rng_pct
    out["volume_displacement_ratio"] = df["volume"] / np.maximum(bar_range, tick_size)
    out["body_displacement_ratio"] = df["volume"] / np.maximum(body, tick_size)

    flag = (
        (vol_pct >= p.absorption_volume_pct)
        & (rng_pct <= p.absorption_range_pct)
        & (body <= p.body_atr_threshold * df["atr_20"])
    )
    # During warmup (any percentile NaN) the flag must be False.
    flag = flag & vol_pct.notna() & rng_pct.notna() & df["atr_20"].notna()
    out["absorption_flag"] = flag.fillna(False).astype(bool)

    # Absorption side from close location within the bar.
    loc = (df["close"] - df["low"]) / np.where(bar_range > 0, bar_range, np.nan)
    side = np.where(loc >= 1.0 - p.close_loc_eps, "bid_absorption",
             np.where(loc <= p.close_loc_eps, "ask_absorption", "unknown"))
    out["absorption_side"] = side

    # Anchors: prior-session high/low/VWAP, current-session VWAP, opening-range,
    # round-number grid. Closest anchor sets anchor_type and absorption_level.
    prior = prior_session_levels(df)
    or_h, or_l = opening_range(df, opening_range_bars=6)
    cur_vwap = session_vwap(df)
    grid = ROUND_NUMBER_GRID_BY_FAMILY.get(family, 5.0)
    round_lvl = df["close"].apply(lambda x: nearest_round_number(x, grid))

    candidates = {
        "prior_session_high": prior["prior_session_high"].values,
        "prior_session_low":  prior["prior_session_low"].values,
        "prior_session_vwap": prior["prior_session_vwap"].values,
        "current_session_vwap": cur_vwap.values,
        "opening_range_high": or_h.values,
        "opening_range_low":  or_l.values,
        "round_number":       round_lvl.values,
    }
    closes = df["close"].values
    atrs = df["atr_20"].values
    n = len(df)
    anchor_type = np.full(n, "", dtype=object)
    anchor_level = np.full(n, np.nan, dtype=float)
    anchor_dist_atr = np.full(n, np.inf, dtype=float)
    for name, arr in candidates.items():
        dist = np.abs(closes - arr)
        # convert to ATR units; ignore NaN atr
        with np.errstate(divide="ignore", invalid="ignore"):
            datr = np.where(atrs > 0, dist / atrs, np.inf)
        better = datr < anchor_dist_atr
        anchor_type[better] = name
        anchor_level[better] = arr[better]
        anchor_dist_atr[better] = datr[better]
    # Tag "none" when no anchor is within range
    no_anchor = anchor_dist_atr > p.anchor_distance_atr
    anchor_type[no_anchor] = "none"
    anchor_level[no_anchor] = np.nan

    out["anchor_type"] = anchor_type
    out["absorption_level"] = anchor_level

    # Expected reversal zone: anchor_level +/- anchor_distance_atr * atr_20.
    rz_half = p.anchor_distance_atr * df["atr_20"]
    out["expected_reversal_zone_low"]  = anchor_level - rz_half
    out["expected_reversal_zone_high"] = anchor_level + rz_half

    # Confidence: 1.0 when flagged AND anchor exists, scaled by how tight the
    # anchor is (closer => higher). 0 when not flagged or no anchor.
    has_anchor = anchor_type != "none"
    base = np.where(out["absorption_flag"].values, 1.0, 0.0)
    # within-range factor in [0, 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        tight = np.where(
            (anchor_dist_atr < np.inf) & (anchor_dist_atr >= 0),
            np.clip(1.0 - (anchor_dist_atr / p.anchor_distance_atr), 0.0, 1.0),
            0.0,
        )
    conf = base * np.where(has_anchor, tight, 0.5)  # half credit if no anchor
    out["absorption_confidence"] = conf

    return out
