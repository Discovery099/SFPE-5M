"""Idea 6 - VPIN-Style Order-Flow Toxicity Proxy.

Operates on source 5-minute bars.

IMPORTANT (spec §6 Idea 6 - literal):
    VPIN was designed for tick-level data. On 5-minute bars, you cannot
    subdivide a single bar into volume buckets. The implementation must
    instead accumulate consecutive 5-minute bars into buckets until the
    cumulative bucket volume reaches `bucket_volume_target`. Each bucket
    therefore contains a variable number of 5-minute bars.

This module respects the clarification: no source 5-minute bar is ever split.
A bucket is closed at the END of the first 5-minute bar that pushes its
cumulative volume at or above the target. Bucket boundaries also reset at
session start.

Bar signing: default `hybrid` per spec.

Output fields:
  vpin_proxy, toxicity_percentile, toxicity_regime, gate_decision, gate_confidence,
  bucket_id, bucket_imbalance (intermediate diagnostics for testing).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .common import causal_percentile_rank


@dataclass
class VpinParams:
    bar_sign_method: str = "hybrid"          # close_open / close_close / hybrid
    session_volume_lookback: int = 20         # sessions for bucket_volume_target
    buckets_per_session_target: int = 50      # spec search includes 25/50/75/100
    vpin_window_buckets: int = 5              # see BLOCKERS.md §21
    toxicity_pct_window_bars: int = 250 * 78  # 250 sessions × 78 RTH bars
    elevated_pct: float = 70.0                # toxicity_regime thresholds
    toxic_pct: float = 90.0
    half_size_pct: float = 70.0               # gate decision thresholds
    stand_down_pct: float = 90.0


def _bar_sign(close: float, open_: float, prev_close: float,
              tick_size: float, method: str) -> float:
    """Per-bar sign per spec §6 Idea 6."""
    if method == "close_open":
        d = close - open_
        return 1.0 if d > 0 else (-1.0 if d < 0 else 0.0)
    if method == "close_close":
        if np.isnan(prev_close):
            d = close - open_
        else:
            d = close - prev_close
        return 1.0 if d > 0 else (-1.0 if d < 0 else 0.0)
    # hybrid: use close_open when |close-open| > tick_size, else close_close
    d = close - open_
    if abs(d) > tick_size:
        return 1.0 if d > 0 else -1.0
    if not np.isnan(prev_close):
        d2 = close - prev_close
        return 1.0 if d2 > 0 else (-1.0 if d2 < 0 else 0.0)
    return 0.0


def compute_vpin(
    df: pd.DataFrame,
    *,
    tick_size: float,
    params: Optional[VpinParams] = None,
) -> pd.DataFrame:
    p = params or VpinParams()
    n = len(df)

    # Causal bucket volume target: rolling median of PRIOR `session_volume_lookback`
    # RTH session totals, divided by `buckets_per_session_target`.
    sess_vol = df.groupby("session_date")["volume"].sum()
    sess_vol_med = (
        sess_vol.shift(1)
                .rolling(window=p.session_volume_lookback,
                         min_periods=p.session_volume_lookback)
                .median()
    )
    target = (sess_vol_med / p.buckets_per_session_target).to_dict()

    out = pd.DataFrame(index=df.index)
    bucket_id_arr = np.full(n, -1, dtype=np.int64)
    bucket_imb_arr = np.full(n, np.nan, dtype=float)
    vpin_proxy_arr = np.full(n, np.nan, dtype=float)
    sign_arr = np.zeros(n, dtype=float)
    signed_vol_arr = np.zeros(n, dtype=float)

    sds = df["session_date"].values
    opens = df["open"].values
    closes = df["close"].values
    vols = df["volume"].values

    # Running per-bucket accumulators
    bucket_global = 0
    bucket_buy_vol = 0.0
    bucket_sell_vol = 0.0
    bucket_total_vol = 0.0
    prev_sd = None
    prev_close = float("nan")
    # Rolling completed-bucket imbalances per session (resets at session start).
    sess_bucket_imbalances: list[float] = []

    for t in range(n):
        sd = sds[t]
        if sd != prev_sd:
            # session boundary: reset bucket state
            bucket_global += 1
            bucket_buy_vol = 0.0
            bucket_sell_vol = 0.0
            bucket_total_vol = 0.0
            prev_sd = sd
            prev_close = float("nan")
            sess_bucket_imbalances = []

        sgn = _bar_sign(closes[t], opens[t], prev_close, tick_size, p.bar_sign_method)
        sign_arr[t] = sgn
        v = vols[t]
        if sgn > 0:
            bucket_buy_vol += v
            signed_vol_arr[t] = v
        elif sgn < 0:
            bucket_sell_vol += v
            signed_vol_arr[t] = -v
        else:
            # flat bar: 50/50 split per spec
            bucket_buy_vol += v / 2.0
            bucket_sell_vol += v / 2.0
            signed_vol_arr[t] = 0.0
        bucket_total_vol += v
        bucket_id_arr[t] = bucket_global
        prev_close = closes[t]

        # Decide if this bar closes the current bucket.
        tgt = target.get(sd, np.nan)
        if not np.isnan(tgt) and tgt > 0 and bucket_total_vol >= tgt:
            imb = (abs(bucket_buy_vol - bucket_sell_vol) / bucket_total_vol
                   if bucket_total_vol > 0 else 0.0)
            bucket_imb_arr[t] = imb
            sess_bucket_imbalances.append(imb)
            if len(sess_bucket_imbalances) >= p.vpin_window_buckets:
                window = sess_bucket_imbalances[-p.vpin_window_buckets:]
                vpin_proxy_arr[t] = float(np.mean(window))
            # start a new bucket on the next bar
            bucket_global += 1
            bucket_buy_vol = 0.0
            bucket_sell_vol = 0.0
            bucket_total_vol = 0.0

    out["bar_sign"] = sign_arr
    out["signed_volume"] = signed_vol_arr
    out["bucket_id"] = bucket_id_arr
    out["bucket_imbalance"] = bucket_imb_arr
    # Forward-fill vpin_proxy within session so non-bucket-close bars carry the
    # last available value. Reset at session start.
    vpin_series = pd.Series(vpin_proxy_arr, index=df.index)
    vpin_series = vpin_series.groupby(df["session_date"].values).ffill()
    out["vpin_proxy"] = vpin_series

    out["toxicity_percentile"] = causal_percentile_rank(
        vpin_series.fillna(0), p.toxicity_pct_window_bars,
    )
    # Regime + gate
    regime = np.where(out["toxicity_percentile"] >= p.toxic_pct, "toxic",
             np.where(out["toxicity_percentile"] >= p.elevated_pct, "elevated", "normal"))
    out["toxicity_regime"] = regime

    gate = np.where(out["toxicity_percentile"] >= p.stand_down_pct, "stand_down",
            np.where(out["toxicity_percentile"] >= p.half_size_pct, "half_size", "allow"))
    out["gate_decision"] = gate
    # gate confidence: distance from the nearest threshold, normalized
    gc = np.where(out["toxicity_percentile"] >= p.stand_down_pct,
                  (out["toxicity_percentile"].values - p.stand_down_pct) / max(100.0 - p.stand_down_pct, 1.0),
          np.where(out["toxicity_percentile"] >= p.half_size_pct,
                  (out["toxicity_percentile"].values - p.half_size_pct) / max(p.stand_down_pct - p.half_size_pct, 1.0),
                  1.0 - out["toxicity_percentile"].values / max(p.half_size_pct, 1.0)))
    gc = np.clip(np.where(np.isfinite(gc), gc, 0.0), 0.0, 1.0)
    out["gate_confidence"] = gc
    return out
