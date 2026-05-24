"""Idea 10 - Synthetic Candle Magnitude Projection and Stress Robustness.

Operates on historical completed synthetic bars (per engine, per instrument).

For each completed synthetic bar i (sorted by close_time), build a categorical
state vector S_i from the state-at-open: (engine, regime, vol_pct, volume_pct,
VPIN_bucket, absorption|vacuum|TPO flags, session_phase). Then, for each bar i,
the PROJECTION quantiles are computed using ONLY bars j < i that match S_i,
with hierarchical pooling per spec.

This function fills the column set for each completed synthetic bar so it can
be joined back to engine outputs and used as a backtest/projection feature.

Spec §6 Idea 10 (literal):
  - default order to drop when pooling (lowest cardinality first):
        session_phase → absorption/vacuum/TPO flags → volume_pct
        → vol_pct → VPIN → regime → engine
  - min_samples_per_state default 30
  - if even fully pooled the dataset is too small: NaN quantiles + state_confidence=0
  - state_confidence = 1.0 at pooling_level=0, decays with pooling level

Output fields:
  expected_abs_return_q20/q50/q80,
  expected_range_q20/q50/q80,
  expected_duration_q20/q50/q80 (in 5-min bars),
  state_confidence, pooling_level, stress_flag
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from .common import session_phase, causal_percentile_rank

# Pooling order: drop from index 0 (lowest cardinality) toward end. The element
# at the end is engine (highest cardinality / most stratifying).
POOLING_ORDER: list[str] = [
    "session_phase", "flag_state", "volume_pct_bucket",
    "vol_pct_bucket", "vpin_bucket", "regime", "engine",
]

# Spec §6 Idea 10 stress windows (US ET dates).
STRESS_WINDOWS = [
    ("covid",  pd.Timestamp("2020-02-20").date(), pd.Timestamp("2020-05-31").date()),
    ("rates",  pd.Timestamp("2022-06-01").date(), pd.Timestamp("2022-10-31").date()),
    ("banks",  pd.Timestamp("2023-03-01").date(), pd.Timestamp("2023-05-31").date()),
]


@dataclass
class MagnitudeProjectionParams:
    min_samples_per_state: int = 30
    quantile_set: tuple = (0.20, 0.50, 0.80)
    tercile_window_bars: int = 500    # causal rolling window for terciles


def _causal_tercile(x: pd.Series, window: int) -> pd.Series:
    """Map a numeric series into low/mid/high terciles via CAUSAL rolling
    percentile (window=`window` past bars). Returns 'unknown' during warmup.
    """
    pct = causal_percentile_rank(x, window)   # in [0, 100]; NaN until warmup
    bins = pd.cut(
        pct, bins=[-0.01, 33.33, 66.67, 100.01],
        labels=["low", "mid", "high"],
    )
    return bins.astype(str).where(pct.notna(), "unknown")


def _stress_flag(session_date) -> bool:
    for _, start, end in STRESS_WINDOWS:
        if start <= session_date <= end:
            return True
    return False


def compute_magnitude_projection(
    synth_bars: pd.DataFrame,
    *,
    source_df: pd.DataFrame,
    feature_regime: pd.DataFrame,
    feature_vpin: pd.DataFrame,
    feature_absorption: pd.DataFrame,
    feature_vacuum: pd.DataFrame,
    feature_tpo: pd.DataFrame,
    expected_bars_per_session: int,
    params: Optional[MagnitudeProjectionParams] = None,
) -> pd.DataFrame:
    """Run the magnitude projection for one (engine, instrument).

    Args:
      synth_bars: DataFrame of completed synthetic bars sorted by close_time.
      source_df:  the source-bar DataFrame this engine consumed.
      feature_*:  per-source-bar feature DataFrames (aligned to source_df.index).

    Returns:
      DataFrame indexed like synth_bars with the spec §6 Idea 10 output columns.
    """
    p = params or MagnitudeProjectionParams()
    if synth_bars.empty:
        return pd.DataFrame()

    # session_phase per source bar
    sphase = session_phase(source_df, expected_bars=expected_bars_per_session)

    # State features per source bar (computed off source_df + features)
    src_state = pd.DataFrame(index=source_df.index)
    src_state["session_phase"] = sphase.values
    src_state["absorption_flag"] = feature_absorption["absorption_flag"].values
    src_state["vacuum_flag"] = feature_vacuum["vacuum_flag"].values
    src_state["tpo_flag"] = feature_tpo["failed_auction_flag"].astype(bool).values
    src_state["flag_state"] = (
        src_state["absorption_flag"].astype(int).astype(str)
        + src_state["vacuum_flag"].astype(int).astype(str)
        + src_state["tpo_flag"].astype(int).astype(str)
    )
    src_state["vpin_bucket"] = feature_vpin["toxicity_regime"].values
    src_state["regime"] = feature_regime["regime_label"].values
    # vol_pct = ATR_20 tercile, volume_pct = volume tercile (research approx).
    src_state["vol_pct_bucket"] = _causal_tercile(source_df["atr_20"], p.tercile_window_bars).values
    src_state["volume_pct_bucket"] = _causal_tercile(source_df["volume"], p.tercile_window_bars).values

    # For each synthetic bar, look up the source-bar STATE at its open index.
    synth = synth_bars.copy().reset_index(drop=True)
    open_states = src_state.iloc[synth["start_idx"].values].reset_index(drop=True)
    state_cols = POOLING_ORDER.copy()
    if "engine" not in synth.columns:
        synth["engine"] = "unknown"
    open_states["engine"] = synth["engine"].values

    # Compute the target variables for each synthetic bar.
    abs_ret = synth["log_return"].abs().values
    synth_range = (synth["high"] - synth["low"]).values
    duration = synth["n_source_bars"].values

    n = len(synth)
    out = pd.DataFrame(index=range(n))
    out["expected_abs_return_q20"] = np.nan
    out["expected_abs_return_q50"] = np.nan
    out["expected_abs_return_q80"] = np.nan
    out["expected_range_q20"] = np.nan
    out["expected_range_q50"] = np.nan
    out["expected_range_q80"] = np.nan
    out["expected_duration_q20"] = np.nan
    out["expected_duration_q50"] = np.nan
    out["expected_duration_q80"] = np.nan
    out["state_confidence"] = 0.0
    out["pooling_level"] = -1
    out["stress_flag"] = False

    # Build cumulative state-keyed indices for fast lookup. The simplest causal
    # approach: walk synth in chronological order, maintaining a dict of
    # state-key -> list of (abs_ret, range, duration). On each new bar, compute
    # the projection from the dict BEFORE adding the bar's own values.
    state_keys: list[str] = []
    for i in range(n):
        keys: list[str] = []
        # build progressively pooled keys by dropping from POOLING_ORDER[0..k]
        full_state = {c: str(open_states.iloc[i].get(c, "")) for c in state_cols}
        for drop_until in range(len(state_cols) + 1):
            kept_cols = state_cols[drop_until:]
            key = "|".join(f"{c}={full_state[c]}" for c in kept_cols)
            keys.append(key)
        state_keys.append(keys)

    # Each per-pool key has its own list of (abs_ret, range, duration).
    pools: dict[str, list[Tuple[float, float, int]]] = {}

    quantiles = np.array(p.quantile_set)

    for i in range(n):
        # Compute projection using existing pools.
        chosen_level = -1
        chosen_quantiles_ret = None
        chosen_quantiles_rng = None
        chosen_quantiles_dur = None
        for level, key in enumerate(state_keys[i]):
            samples = pools.get(key, [])
            if len(samples) >= p.min_samples_per_state:
                arr = np.array(samples)
                chosen_quantiles_ret = np.quantile(arr[:, 0], quantiles)
                chosen_quantiles_rng = np.quantile(arr[:, 1], quantiles)
                chosen_quantiles_dur = np.quantile(arr[:, 2], quantiles)
                chosen_level = level
                break
        if chosen_level >= 0:
            out.at[i, "expected_abs_return_q20"] = chosen_quantiles_ret[0]
            out.at[i, "expected_abs_return_q50"] = chosen_quantiles_ret[1]
            out.at[i, "expected_abs_return_q80"] = chosen_quantiles_ret[2]
            out.at[i, "expected_range_q20"] = chosen_quantiles_rng[0]
            out.at[i, "expected_range_q50"] = chosen_quantiles_rng[1]
            out.at[i, "expected_range_q80"] = chosen_quantiles_rng[2]
            out.at[i, "expected_duration_q20"] = chosen_quantiles_dur[0]
            out.at[i, "expected_duration_q50"] = chosen_quantiles_dur[1]
            out.at[i, "expected_duration_q80"] = chosen_quantiles_dur[2]
            out.at[i, "pooling_level"] = chosen_level
            # state_confidence: 1.0 at level 0, decays geometrically
            out.at[i, "state_confidence"] = 1.0 / (1 + chosen_level)
        # else: leave NaN + state_confidence=0

        # stress flag for the synthetic bar's session
        sd = synth.iloc[i]["session_date"]
        try:
            sd_d = pd.Timestamp(sd).date() if not isinstance(sd, pd.Timestamp) else sd.date()
            if isinstance(sd, str):
                sd_d = pd.Timestamp(sd).date()
        except Exception:
            sd_d = sd
        try:
            out.at[i, "stress_flag"] = _stress_flag(sd_d)
        except Exception:
            out.at[i, "stress_flag"] = False

        # NOW add this synthetic bar to all pool levels (so subsequent bars can see it)
        for key in state_keys[i]:
            pools.setdefault(key, []).append((abs_ret[i], synth_range[i], duration[i]))

    return out
