"""Idea 9 - Roll-Spread × Variance-Ratio Regime Router.

Operates on source 5-minute bars.

Spec §6 Idea 9 (literal):
  r_t = close_t - close_{t-1}   (within-session only)
  cov_t = rolling_cov(r_t, r_{t-1}, window=roll_window)
  roll_spread_t = 2 * sqrt(max(-cov_t, 0))

  1_bar_var  = rolling_var(r_t, window=vr_window)
  q_bar_returns  = sum of r over non-overlapping q-bar windows
  q_bar_var  = rolling_var(q_bar_returns, window=vr_window/q)
  VR(q) = q_bar_var / (q * 1_bar_var)

BLOCKERS.md §19 documents the use of an OVERLAPPING rolling sum for q-bar
returns (Lo & MacKinlay's standard variant), as the non-overlapping version is
statistically less robust and the spec did not explicitly forbid overlapping.

Regime labels:
  spread_wide AND vr_meanrev -> "noise_mean_reverting"
  spread_tight AND vr_trending -> "informed_trending"
  spread_wide AND vr_trending -> "stressed_illiquid"
  spread_tight AND vr_meanrev -> "balanced_or_choppy"
  else -> "ambiguous"

Output fields:
  roll_spread_proxy, variance_ratio, spread_percentile, vr_percentile,
  regime_label, regime_confidence, allowed_strategy_family
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from .common import causal_percentile_rank, within_session_diff


@dataclass
class RegimeParams:
    # Defaults: tightest end of spec search ranges to maximize per-session
    # coverage (BLOCKERS.md §19).
    roll_window: int = 30
    vr_window: int = 30
    vr_q: int = 3
    spread_wide_pct: float = 70.0
    spread_tight_pct: float = 30.0
    regime_confidence_threshold: float = 0.55
    rolling_session_window_bars: int = 250 * 78    # 250 sessions × 78 RTH bars


def compute_regime(
    df: pd.DataFrame,
    *,
    params: Optional[RegimeParams] = None,
) -> pd.DataFrame:
    p = params or RegimeParams()
    out = pd.DataFrame(index=df.index)

    r = within_session_diff(df["close"], df["session_date"])
    r_prev = r.shift(1)
    # Strictly causal, session-aware rolling: reset stats at session start so
    # we don't carry cross-session noise into the regime estimate. pandas
    # groupby(...).rolling() with min_periods=window guarantees no leakage.
    rr = r * r_prev
    sd = df["session_date"]
    cov = (
        rr.groupby(sd)
          .rolling(window=p.roll_window, min_periods=p.roll_window)
          .mean()
          .reset_index(level=0, drop=True)
    )
    cov = cov.reindex(df.index)
    roll_spread = 2.0 * np.sqrt(np.maximum(-cov, 0.0))
    out["roll_spread_proxy"] = roll_spread

    # Variance ratio (overlapping q-bar rolling sum, Lo-MacKinlay variant) -
    # also session-aware to avoid cross-session contamination.
    one_var = (
        r.groupby(sd)
         .rolling(window=p.vr_window, min_periods=p.vr_window)
         .var(ddof=0)
         .reset_index(level=0, drop=True)
    ).reindex(df.index)
    q_sum = (
        r.groupby(sd)
         .rolling(window=p.vr_q, min_periods=p.vr_q)
         .sum()
         .reset_index(level=0, drop=True)
    ).reindex(df.index)
    q_var = (
        q_sum.groupby(sd)
             .rolling(window=p.vr_window, min_periods=p.vr_window)
             .var(ddof=0)
             .reset_index(level=0, drop=True)
    ).reindex(df.index)
    vr = q_var / (p.vr_q * one_var.replace(0, np.nan))
    out["variance_ratio"] = vr

    spread_pct = causal_percentile_rank(roll_spread.fillna(0), p.rolling_session_window_bars)
    vr_pct = causal_percentile_rank(vr.fillna(0), p.rolling_session_window_bars)
    out["spread_percentile"] = spread_pct
    out["vr_percentile"] = vr_pct

    spread_wide = spread_pct >= p.spread_wide_pct
    spread_tight = spread_pct <= p.spread_tight_pct
    vr_trending = vr > 1.0
    vr_meanrev = vr < 1.0

    label = np.full(len(df), "ambiguous", dtype=object)
    label[(spread_wide & vr_meanrev).fillna(False).values] = "noise_mean_reverting"
    label[(spread_tight & vr_trending).fillna(False).values] = "informed_trending"
    label[(spread_wide & vr_trending).fillna(False).values] = "stressed_illiquid"
    label[(spread_tight & vr_meanrev).fillna(False).values] = "balanced_or_choppy"

    # confidence: distance of spread_pct from its threshold + distance of VR
    # from 1.0, normalized into [0, 1]. For bars in the "ambiguous" middle band
    # of spread_pct, use 0 spread contribution (they don't pick a side).
    sd_spread = np.where(
        spread_wide.fillna(False).values,
        (spread_pct.values - p.spread_wide_pct) / max(100.0 - p.spread_wide_pct, 1.0),
        np.where(spread_tight.fillna(False).values,
                 (p.spread_tight_pct - spread_pct.values) / max(p.spread_tight_pct, 1.0),
                 0.0)
    )
    sd_spread = np.clip(np.where(np.isfinite(sd_spread), sd_spread, 0.0), 0.0, 1.0)
    # VR confidence: scaled |VR - 1|, doubled so VR=0.5 or 1.5 give full
    # confidence (well outside the random-walk null).
    sd_vr = np.clip(2.0 * np.abs(vr.values - 1.0), 0.0, 1.0)
    sd_vr = np.where(np.isfinite(sd_vr), sd_vr, 0.0)
    conf = (sd_spread + sd_vr) / 2.0
    conf = np.where(np.isfinite(conf), conf, 0.0)
    out["regime_confidence"] = conf
    # override low-confidence labels
    low = conf < p.regime_confidence_threshold
    label[low] = "stand_down"
    out["regime_label"] = label

    # allowed_strategy_family per label
    family_map = {
        "noise_mean_reverting": ["mean_reversion"],
        "informed_trending":   ["continuation"],
        "stressed_illiquid":   ["stand_down"],
        "balanced_or_choppy":  ["mean_reversion", "continuation"],
        "ambiguous":           ["stand_down"],
        "stand_down":          ["stand_down"],
    }
    out["allowed_strategy_family"] = [";".join(family_map[x]) for x in label]
    return out
