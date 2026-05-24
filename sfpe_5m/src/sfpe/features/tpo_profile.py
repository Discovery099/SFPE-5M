"""Idea 7 - Failed-Auction / TPO Market Profile Completion.

Operates on source 5-minute RTH bars. Partition each RTH session into 30-minute
TPO periods (six 5-minute bars per period). The last period of each session may
be partial:
  - merge it into the previous period if it has < 3 bars
  - otherwise treat as a normal period

POC tie-breaker (BLOCKERS.md §22): bucket closest to session VWAP.

Profile construction:
  1. Build price buckets using `bucket_size_ticks * tick_size`.
  2. For each period, mark every bucket the period's bars touched (high..low).
  3. Count how many periods touched each bucket.
  4. POC = max-count bucket (tie-break = closest to session VWAP).
  5. Value area = contiguous range around POC containing `value_area_pct` of
     total TPO counts; expand symmetrically from POC, each step adding the
     side with higher count.
  6. VAH / VAL = top / bottom of value area.

Failed-auction detection (per spec, literal):
  failed_auction_up_session_N =
      (high_N > prior_VAH)
      AND (close_N < prior_VAH)
      AND (TPO count in the extreme bucket above prior_VAH <= thin_tpo_threshold)
  failed_auction_down_session_N analogously.

Output fields (per-source-bar): VAH_prior, VAL_prior, POC_prior,
  value_midpoint_prior, failed_auction_flag, failed_auction_side, target_level,
  tpo_confidence.

For research/Phase-3 use: failed_auction values are computed for each session
and broadcast to every bar in session N+1 (so a trading model only ever sees
last-session's failed-auction state -- strictly causal).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from .common import session_vwap


@dataclass
class TpoParams:
    bucket_size_ticks: int = 2
    value_area_pct: float = 70.0
    thin_tpo_threshold: int = 2
    failed_return_window_bars: int = 6
    target_policy: str = "POC"   # POC / VA_midpoint / opposite_value_edge
    bars_per_period: int = 6     # 30 minutes / 5 minutes


def _build_profile(period_bars: list[Tuple[float, float]], bucket: float) -> dict[float, int]:
    """Build a TPO count dict: {bucket_price: count} for the given list of periods.

    A period is a (lo, hi) tuple of the period's overall low and high.
    """
    counts: dict[float, int] = {}
    for lo, hi in period_bars:
        if not (np.isfinite(lo) and np.isfinite(hi)):
            continue
        b_lo = int(np.floor(lo / bucket))
        b_hi = int(np.floor(hi / bucket))
        for b in range(b_lo, b_hi + 1):
            counts[b * bucket] = counts.get(b * bucket, 0) + 1
    return counts


def _value_area(counts: dict[float, int], poc: float, target_count: int) -> Tuple[float, float]:
    """Expand symmetrically from POC, each step adding the side with higher count,
    until cumulative count >= target. Return (VAL, VAH)."""
    if not counts:
        return (np.nan, np.nan)
    keys = sorted(counts.keys())
    poc_idx = keys.index(poc)
    lo_idx = poc_idx
    hi_idx = poc_idx
    cum = counts[poc]
    while cum < target_count and (lo_idx > 0 or hi_idx < len(keys) - 1):
        up_count = counts[keys[hi_idx + 1]] if hi_idx < len(keys) - 1 else -1
        down_count = counts[keys[lo_idx - 1]] if lo_idx > 0 else -1
        if up_count >= down_count and hi_idx < len(keys) - 1:
            hi_idx += 1
            cum += counts[keys[hi_idx]]
        elif lo_idx > 0:
            lo_idx -= 1
            cum += counts[keys[lo_idx]]
        else:
            break
    return keys[lo_idx], keys[hi_idx]


def compute_tpo(
    df: pd.DataFrame,
    *,
    tick_size: float,
    params: Optional[TpoParams] = None,
) -> pd.DataFrame:
    p = params or TpoParams()
    bucket = p.bucket_size_ticks * tick_size

    vwap = session_vwap(df)

    # First pass: build per-session TPO profiles.
    session_profiles: dict[object, dict] = {}
    for sd, g in df.groupby("session_date", sort=False):
        # Partition into periods of bars_per_period source bars.
        idxs = g.index.tolist()
        # last period merge rule: if last period has < 3 bars, merge into prev.
        nbars = len(idxs)
        nperiods = nbars // p.bars_per_period
        last_partial = nbars - nperiods * p.bars_per_period
        period_bars: list[Tuple[float, float]] = []
        cur_idx = 0
        for k in range(nperiods):
            sub_idx = idxs[cur_idx: cur_idx + p.bars_per_period]
            sub = g.loc[sub_idx]
            period_bars.append((sub["low"].min(), sub["high"].max()))
            cur_idx += p.bars_per_period
        if last_partial >= 3:
            sub = g.loc[idxs[cur_idx:]]
            period_bars.append((sub["low"].min(), sub["high"].max()))
        elif last_partial > 0:
            # merge into the previous period
            sub_idx = idxs[max(cur_idx - p.bars_per_period, 0):]
            sub = g.loc[sub_idx]
            if period_bars:
                period_bars[-1] = (sub["low"].min(), sub["high"].max())
            else:
                period_bars.append((sub["low"].min(), sub["high"].max()))

        counts = _build_profile(period_bars, bucket)
        if not counts:
            session_profiles[sd] = dict(
                poc=np.nan, vah=np.nan, val=np.nan, val_midpoint=np.nan,
                counts={}, total=0,
            )
            continue
        max_count = max(counts.values())
        candidates = [k for k, c in counts.items() if c == max_count]
        sess_vwap_val = vwap.loc[g.index].iloc[-1] if len(g) else np.nan
        if not np.isnan(sess_vwap_val):
            poc = min(candidates, key=lambda k: abs(k - sess_vwap_val))
        else:
            poc = candidates[len(candidates) // 2]
        total = sum(counts.values())
        target_cnt = int(np.ceil(total * p.value_area_pct / 100.0))
        val, vah = _value_area(counts, poc, target_cnt)
        val_mid = (val + vah) / 2.0
        session_profiles[sd] = dict(
            poc=poc, vah=vah, val=val, val_midpoint=val_mid,
            counts=counts, total=total,
        )

    # Second pass: compute failed_auction per session (per-session scope, but
    # only used to drive the broadcast for the NEXT session, so signal usage
    # is strictly causal).
    sessions = list(session_profiles.keys())
    fa_up = {}
    fa_down = {}
    for i, sd in enumerate(sessions):
        if i == 0:
            fa_up[sd] = False
            fa_down[sd] = False
            continue
        prior = session_profiles[sessions[i - 1]]
        cur = session_profiles[sd]
        # cur session bars
        sub = df[df["session_date"] == sd]
        if sub.empty or np.isnan(prior["vah"]) or np.isnan(prior["val"]):
            fa_up[sd] = False
            fa_down[sd] = False
            continue
        hi = sub["high"].max()
        lo = sub["low"].min()
        cl = sub["close"].iloc[-1]
        # extreme bucket above prior_VAH in cur session's profile
        bucket = p.bucket_size_ticks * tick_size
        cur_counts = cur["counts"]
        extreme_above = max([k for k in cur_counts if k > prior["vah"]], default=None)
        extreme_below = min([k for k in cur_counts if k < prior["val"]], default=None)
        fa_up[sd] = (hi > prior["vah"]) and (cl < prior["vah"]) and (
            extreme_above is not None
            and cur_counts.get(extreme_above, 0) <= p.thin_tpo_threshold
        )
        fa_down[sd] = (lo < prior["val"]) and (cl > prior["val"]) and (
            extreme_below is not None
            and cur_counts.get(extreme_below, 0) <= p.thin_tpo_threshold
        )

    # Third pass: broadcast prior session's POC/VAH/VAL + failed_auction state
    # to every bar in the NEXT session. Strictly causal.
    out_rows = []
    for sd, g in df.groupby("session_date", sort=False):
        idxs = g.index.tolist()
        i = sessions.index(sd)
        if i == 0:
            prior_poc = np.nan
            prior_vah = np.nan
            prior_val = np.nan
            prior_mid = np.nan
            fa_flag = False
            fa_side = 0
        else:
            prior = session_profiles[sessions[i - 1]]
            prior_poc = prior["poc"]
            prior_vah = prior["vah"]
            prior_val = prior["val"]
            prior_mid = prior["val_midpoint"]
            prior_fa_up = fa_up.get(sessions[i - 1], False)
            prior_fa_down = fa_down.get(sessions[i - 1], False)
            fa_flag = bool(prior_fa_up or prior_fa_down)
            fa_side = 1 if prior_fa_up else (-1 if prior_fa_down else 0)
        # target_level per target_policy
        if p.target_policy == "POC":
            target = prior_poc
        elif p.target_policy == "VA_midpoint":
            target = prior_mid
        else:                 # opposite_value_edge
            target = prior_val if fa_side > 0 else (prior_vah if fa_side < 0 else np.nan)
        # tpo confidence: 1.0 when failed_auction flagged, else 0
        conf = 1.0 if fa_flag else 0.0
        for idx in idxs:
            out_rows.append((idx, prior_vah, prior_val, prior_poc, prior_mid,
                             fa_flag, fa_side, target, conf))

    out = pd.DataFrame(out_rows, columns=[
        "_idx", "VAH_prior", "VAL_prior", "POC_prior", "value_midpoint_prior",
        "failed_auction_flag", "failed_auction_side", "target_level", "tpo_confidence",
    ]).set_index("_idx").reindex(df.index)
    return out
