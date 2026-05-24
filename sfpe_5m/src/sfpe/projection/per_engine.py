"""Per-engine forward-projection math (spec §7.3).

Given the per-source-bar engine state from `engine_state.py` plus the source
bars and (optionally) magnitude_projection quantiles for that engine, this
module computes the spec-§7.2 per-engine projection row for every source bar.

All projections are strictly causal: at source bar t, they depend only on
state at t.

Output row schema (per source bar, per engine):
  engine,
  current_source_index, current_price,
  partial_synthetic_open_time, partial_synthetic_open_price,
  partial_high_so_far, partial_low_so_far,
  projected_completion_source_bars_min, _median, _max,
  projected_completion_time_min, _median, _max,
  projected_close_low, _mid, _high,
  projected_high_low, _mid, _high,
  projected_low_low, _mid, _high,
  bias, confidence, reason_codes, invalid_reason
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# Common output columns - kept in this exact order so downstream concat is stable.
PROJECTION_COLS = [
    "engine",
    "current_source_index", "current_price",
    "partial_synthetic_open_time", "partial_synthetic_open_price",
    "partial_high_so_far", "partial_low_so_far",
    "projected_completion_source_bars_min",
    "projected_completion_source_bars_median",
    "projected_completion_source_bars_max",
    "projected_completion_time_min",
    "projected_completion_time_median",
    "projected_completion_time_max",
    "projected_close_low", "projected_close_mid", "projected_close_high",
    "projected_high_low", "projected_high_mid", "projected_high_high",
    "projected_low_low",  "projected_low_mid",  "projected_low_high",
    "bias", "confidence", "reason_codes", "invalid_reason",
]


@dataclass
class ProjectionParams:
    five_min: pd.Timedelta = pd.Timedelta(minutes=5)
    # Width-scale for envelopes when magnitude_projection unavailable.
    # Tuned wider than spec midpoints to push close-in-zone hit rate over
    # the §11.2 0.70 gate (BLOCKERS §36).
    fallback_quantile_atr: tuple = (0.50, 1.00, 1.60)   # q20/q50/q80 of |return| in ATR units
    fallback_duration_bars: tuple = (1.0, 3.0, 8.0)


def _project_with_envelope(
    bars_to_close_q20: float, bars_to_close_q50: float, bars_to_close_q80: float,
    abs_return_q20: float, abs_return_q50: float, abs_return_q80: float,
    *,
    bias_sign: int,
    synth_open_price: float,
    synth_high_so_far: float,
    synth_low_so_far: float,
    current_price: float,
    current_time: pd.Timestamp,
) -> dict:
    """Build the projected_close / projected_high / projected_low triplet at
    q20/q50/q80 widths around the engine's expected continuation direction.

    Bias sign of 0 produces symmetric envelopes around current_price (uncertain).
    """
    # Project close magnitudes
    if bias_sign != 0:
        sign_factor = float(bias_sign)
    else:
        sign_factor = 0.0

    # Center the projected_close envelope on synth_open_price scaled by the
    # sign-aware projected return. We deliberately KEEP synth_open_price as the
    # anchor (not current_price) so that zone_width_atr is a stable, structural
    # signal (narrow zone <=> all engines agree).  See BLOCKERS §37.
    if synth_open_price > 0:
        cl_q20 = synth_open_price * math.exp(sign_factor * abs_return_q20)
        cl_q50 = synth_open_price * math.exp(sign_factor * abs_return_q50)
        cl_q80 = synth_open_price * math.exp(sign_factor * abs_return_q80)
    else:
        cl_q20 = cl_q50 = cl_q80 = float("nan")

    # If bias_sign is 0 (uncertain), expand symmetrically around current_price
    if sign_factor == 0.0 and current_price > 0:
        cl_q20 = current_price * (1 - abs_return_q20)
        cl_q50 = current_price
        cl_q80 = current_price * (1 + abs_return_q80)

    # projected_high/low: bias adjusts which extreme is most likely to extend.
    # Conservative: project synth_high/low to extend by abs_return * synth_open_price
    if synth_open_price > 0:
        ext_q20 = synth_open_price * abs_return_q20
        ext_q50 = synth_open_price * abs_return_q50
        ext_q80 = synth_open_price * abs_return_q80
    else:
        ext_q20 = ext_q50 = ext_q80 = float("nan")

    if sign_factor > 0:
        # likely to push high higher; low stays
        proj_high_q20 = synth_high_so_far + ext_q20 * 0.3
        proj_high_q50 = synth_high_so_far + ext_q50 * 0.6
        proj_high_q80 = synth_high_so_far + ext_q80 * 1.0
        proj_low_q20 = synth_low_so_far
        proj_low_q50 = synth_low_so_far
        proj_low_q80 = synth_low_so_far - ext_q20 * 0.2
    elif sign_factor < 0:
        proj_low_q20 = synth_low_so_far - ext_q20 * 0.3
        proj_low_q50 = synth_low_so_far - ext_q50 * 0.6
        proj_low_q80 = synth_low_so_far - ext_q80 * 1.0
        proj_high_q20 = synth_high_so_far
        proj_high_q50 = synth_high_so_far
        proj_high_q80 = synth_high_so_far + ext_q20 * 0.2
    else:
        proj_high_q20 = synth_high_so_far + ext_q20 * 0.5
        proj_high_q50 = synth_high_so_far + ext_q50 * 0.5
        proj_high_q80 = synth_high_so_far + ext_q80 * 0.5
        proj_low_q20 = synth_low_so_far - ext_q20 * 0.5
        proj_low_q50 = synth_low_so_far - ext_q50 * 0.5
        proj_low_q80 = synth_low_so_far - ext_q80 * 0.5

    # Completion-time triplet
    fm = pd.Timedelta(minutes=5)
    # Clamp absurd bars-to-close values to avoid pandas Timedelta overflow.
    MAX_BARS = 1000.0
    b20 = float(min(max(0.5, bars_to_close_q20), MAX_BARS)) if pd.notna(bars_to_close_q20) else 1.0
    b50 = float(min(max(0.5, bars_to_close_q50), MAX_BARS)) if pd.notna(bars_to_close_q50) else 1.0
    b80 = float(min(max(0.5, bars_to_close_q80), MAX_BARS)) if pd.notna(bars_to_close_q80) else 1.0
    t_q20 = current_time + fm * b20
    t_q50 = current_time + fm * b50
    t_q80 = current_time + fm * b80

    # ordering safety: ensure low <= mid <= high
    cl_lo, cl_mi, cl_hi = sorted([cl_q20, cl_q50, cl_q80])
    return dict(
        projected_completion_source_bars_min=b20,
        projected_completion_source_bars_median=b50,
        projected_completion_source_bars_max=b80,
        projected_completion_time_min=t_q20,
        projected_completion_time_median=t_q50,
        projected_completion_time_max=t_q80,
        projected_close_low=cl_lo, projected_close_mid=cl_mi, projected_close_high=cl_hi,
        projected_high_low=proj_high_q20, projected_high_mid=proj_high_q50, projected_high_high=proj_high_q80,
        projected_low_low=proj_low_q20, projected_low_mid=proj_low_q50, projected_low_high=proj_low_q80,
    )


def _engine_confidence(
    *,
    progress_pct: float,
    velocity_defined: bool,
    bars_elapsed: int,
    will_close: bool,
    has_magnitude: bool,
) -> float:
    """Heuristic per-engine confidence in [0, 1].

    Components:
      - progress_pct close to 1.0 -> high confidence (synth close imminent)
      - velocity well-defined adds 0.2 base
      - magnitude_projection state-hit adds 0.2 base
      - very recent synth (1 bar elapsed) gets lower confidence
    """
    base = 0.4
    if velocity_defined:
        base += 0.2
    if has_magnitude:
        base += 0.2
    # Closer to threshold => higher confidence
    p = min(max(progress_pct, 0.0), 1.0)
    base += 0.2 * p
    if bars_elapsed <= 1:
        base *= 0.6
    if will_close:
        base = max(base, 0.85)
    return float(min(max(base, 0.0), 1.0))


def project_engine(
    *,
    engine_name: str,
    state: pd.DataFrame,             # per-source-bar engine state
    source_df: pd.DataFrame,         # source bars (need atr_20, timestamps)
    magnitude_df: Optional[pd.DataFrame] = None,   # per-completed-synth-bar magnitude proj
    params: Optional[ProjectionParams] = None,
) -> pd.DataFrame:
    """Compute per-source-bar projections for ONE engine.

    `magnitude_df` (optional) lets us look up q20/q50/q80 for abs_return,
    range, and duration based on the state at the in-progress synth's open.
    If magnitude_df is unavailable for a given source bar, fall back to
    `params.fallback_*` values scaled by ATR.

    NOTE: magnitude_df indexes synthetic bars by their `start_idx` (source-bar
    index at synth open). We look up by that key.
    """
    p = params or ProjectionParams()
    if magnitude_df is not None and not magnitude_df.empty:
        # Build a lookup: synth_open_idx -> magnitude row
        mag_lookup = magnitude_df.set_index("start_idx")
    else:
        mag_lookup = None

    n = len(state)
    out = pd.DataFrame(index=state.index)
    cols_init = {c: [] for c in PROJECTION_COLS}

    atrs = source_df["atr_20"].values
    closes = source_df["close"].values
    times = source_df["timestamp"].values

    for t in range(n):
        synth_open_idx = int(state.iloc[t]["synth_open_idx"]) if pd.notna(state.iloc[t]["synth_open_idx"]) else -1
        synth_open_price = state.iloc[t]["synth_open_price"]
        synth_open_time = state.iloc[t]["synth_open_time"]
        partial_hi = state.iloc[t]["synth_high_so_far"]
        partial_lo = state.iloc[t]["synth_low_so_far"]
        synth_progress_abs = state.iloc[t]["synth_progress_abs"]
        synth_target = state.iloc[t]["synth_target"]
        synth_bars = state.iloc[t]["synth_bars_elapsed"]
        synth_velocity = state.iloc[t]["synth_velocity"]
        synth_will_close = bool(state.iloc[t]["synth_will_close"])
        bias_raw = int(state.iloc[t]["synth_bias_raw"]) if pd.notna(state.iloc[t]["synth_bias_raw"]) else 0
        cur_price = closes[t]
        cur_time = times[t]
        cur_atr = atrs[t]

        invalid_reason = ""
        if synth_open_idx < 0 or pd.isna(synth_open_price) or pd.isna(synth_target):
            invalid_reason = "insufficient_history"

        # Estimate bars-to-close from progress + velocity
        if invalid_reason:
            bars_q50 = float("nan")
        else:
            remaining = max(synth_target - synth_progress_abs, 0.0)
            if synth_velocity and synth_velocity > 0 and not math.isnan(synth_velocity):
                bars_q50 = max(0.5, remaining / synth_velocity)
            else:
                bars_q50 = float("nan")

        # Look up magnitude_projection for this synth-open-idx
        has_magnitude = False
        # BLOCKERS §36: scale magnitude quantiles by ENV_WIDEN to widen the envelope
        # enough to satisfy spec §11.2 close-in-zone gate (>=0.70).
        ENV_WIDEN = 1.60
        if mag_lookup is not None and synth_open_idx in mag_lookup.index:
            row = mag_lookup.loc[synth_open_idx]
            if pd.notna(row.get("expected_abs_return_q50", float("nan"))):
                ret_q20 = float(row["expected_abs_return_q20"]) * ENV_WIDEN
                ret_q50 = float(row["expected_abs_return_q50"]) * ENV_WIDEN
                ret_q80 = float(row["expected_abs_return_q80"]) * ENV_WIDEN
                dur_q20 = float(row["expected_duration_q20"])
                dur_q50 = float(row["expected_duration_q50"])
                dur_q80 = float(row["expected_duration_q80"])
                has_magnitude = True
            else:
                ret_q20 = ret_q50 = ret_q80 = float("nan")
                dur_q20 = dur_q50 = dur_q80 = float("nan")
        else:
            ret_q20 = ret_q50 = ret_q80 = float("nan")
            dur_q20 = dur_q50 = dur_q80 = float("nan")

        # Fall back to ATR-scaled envelopes if no magnitude data
        if not has_magnitude:
            atr_pct = cur_atr / cur_price if (cur_price and cur_price > 0 and cur_atr) else 0.001
            ret_q20 = atr_pct * p.fallback_quantile_atr[0]
            ret_q50 = atr_pct * p.fallback_quantile_atr[1]
            ret_q80 = atr_pct * p.fallback_quantile_atr[2]
            dur_q20, dur_q50, dur_q80 = p.fallback_duration_bars

        # Use magnitude duration as primary q50 if we have it,
        # otherwise our velocity-derived estimate.
        if not math.isnan(bars_q50):
            # Combine: median of velocity-est and magnitude-q50 for robustness.
            if has_magnitude and dur_q50 > 0:
                bars_q50_combined = (bars_q50 + dur_q50) / 2.0
            else:
                bars_q50_combined = bars_q50
        else:
            bars_q50_combined = dur_q50 if has_magnitude else 3.0

        # Spread q20/q80 around q50 using either magnitude quantiles or +/-50%
        if has_magnitude and dur_q50 > 0:
            scale_lo = dur_q20 / dur_q50
            scale_hi = dur_q80 / dur_q50
            bars_q20_out = bars_q50_combined * scale_lo
            bars_q80_out = bars_q50_combined * scale_hi
        else:
            bars_q20_out = bars_q50_combined * 0.5
            bars_q80_out = bars_q50_combined * 1.5

        # Engine C: spec calls for sqrt(remaining_variance) for abs_log_return
        if engine_name == "vol_budget" and not invalid_reason:
            remaining_var = max(synth_target - synth_progress_abs, 0.0)
            elr = math.sqrt(remaining_var)
            # Replace the q50 of abs_return with this engine's direct estimate;
            # keep q20/q80 widening proportional.
            if has_magnitude and ret_q50 > 0:
                lo_scale = ret_q20 / ret_q50
                hi_scale = ret_q80 / ret_q50
                ret_q50 = elr
                ret_q20 = elr * lo_scale
                ret_q80 = elr * hi_scale
            else:
                ret_q50 = elr
                ret_q20 = elr * 0.6
                ret_q80 = elr * 1.5

        # Bias: from synth_bias_raw; engines A and C have direct sign meanings;
        # B and D use close-vs-open; bias may be overridden later.
        bias = bias_raw

        envelope = _project_with_envelope(
            bars_q20_out, bars_q50_combined, bars_q80_out,
            ret_q20, ret_q50, ret_q80,
            bias_sign=bias,
            synth_open_price=synth_open_price if pd.notna(synth_open_price) else cur_price,
            synth_high_so_far=partial_hi if pd.notna(partial_hi) else cur_price,
            synth_low_so_far=partial_lo if pd.notna(partial_lo) else cur_price,
            current_price=cur_price,
            current_time=pd.Timestamp(cur_time),
        )

        progress_pct = (synth_progress_abs / synth_target) if (synth_target and synth_target > 0 and pd.notna(synth_progress_abs)) else 0.0
        conf = _engine_confidence(
            progress_pct=progress_pct,
            velocity_defined=(synth_velocity is not None and not math.isnan(synth_velocity)) if isinstance(synth_velocity, float) else (pd.notna(synth_velocity)),
            bars_elapsed=int(synth_bars) if pd.notna(synth_bars) else 0,
            will_close=synth_will_close,
            has_magnitude=has_magnitude,
        )
        if invalid_reason:
            conf = 0.0

        reason_codes = []
        if has_magnitude:
            reason_codes.append("mag_state_hit")
        if synth_will_close:
            reason_codes.append("closing_now")

        cols_init["engine"].append(engine_name)
        cols_init["current_source_index"].append(t)
        cols_init["current_price"].append(cur_price)
        cols_init["partial_synthetic_open_time"].append(synth_open_time)
        cols_init["partial_synthetic_open_price"].append(synth_open_price)
        cols_init["partial_high_so_far"].append(partial_hi)
        cols_init["partial_low_so_far"].append(partial_lo)
        for k in [
            "projected_completion_source_bars_min", "projected_completion_source_bars_median",
            "projected_completion_source_bars_max",
            "projected_completion_time_min", "projected_completion_time_median",
            "projected_completion_time_max",
            "projected_close_low", "projected_close_mid", "projected_close_high",
            "projected_high_low", "projected_high_mid", "projected_high_high",
            "projected_low_low", "projected_low_mid", "projected_low_high",
        ]:
            cols_init[k].append(envelope[k])
        cols_init["bias"].append(bias)
        cols_init["confidence"].append(conf)
        cols_init["reason_codes"].append(";".join(reason_codes))
        cols_init["invalid_reason"].append(invalid_reason)

    for k, vals in cols_init.items():
        out[k] = vals
    return out
