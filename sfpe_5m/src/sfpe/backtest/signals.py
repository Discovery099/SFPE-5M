"""Phase 5 signal generation utilities.

The Phase-4 ensemble CSV (`features/projection_ensemble__<SYM>.csv`) has a
broken `trade_eligible` column (BLOCKERS §38 -- UTC vs ET timestamp bug). This
module recomputes per-bar trade eligibility from the underlying gate columns
plus a properly tz-aware source timestamp + a confidence threshold.

Outputs a per-source-bar DataFrame aligned 1:1 with the source loader frame,
providing the inputs the EventEngine expects (`bias`, `trade_eligible`,
`ensemble_confidence`, optional features for cost models).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class EligibilityParams:
    min_agreement: int = 3
    max_zone_width_atr: float = 1.5
    max_horizon_bars: int = 12
    # latest_entry_time is supplied per-instrument by the runner ("15:30" for
    # equities, "14:00" for MCL, "13:00" for MGC).
    latest_entry_time_et: str = "15:30"
    # Confidence threshold ("0.50" or "0.65" per user spec for Phase 5).
    min_confidence: float = 0.65


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def recompute_trade_eligibility(
    *,
    ensemble_csv: Path,
    source_df: pd.DataFrame,
    regime_csv: Optional[Path] = None,
    params: Optional[EligibilityParams] = None,
) -> pd.DataFrame:
    """Return a per-bar signal frame for the EventEngine.

    `source_df` must be the OUTPUT of `loader.load_instrument_csv()` -- it has
    a tz-aware `timestamp` column in `America/New_York`. The ensemble CSV has
    naive UTC timestamps; we align by row position (both are aligned 1:1 with
    the source bar sequence).
    """
    p = params or EligibilityParams()
    ens = pd.read_csv(ensemble_csv)
    if len(ens) != len(source_df):
        raise ValueError(
            f"ensemble CSV row count {len(ens):,} != source row count "
            f"{len(source_df):,}; alignment broken"
        )

    # tz-aware ET hour-of-day from the source loader.
    et_hour = source_df["timestamp"].dt.hour.values
    et_min = source_df["timestamp"].dt.minute.values
    cut_h, cut_m = _parse_hhmm(p.latest_entry_time_et)
    pre_cutoff = (et_hour * 60 + et_min) < (cut_h * 60 + cut_m)

    # Gate checks (vectorised).
    agree_ok = ens["agreement_count"].fillna(0).astype(int).values >= p.min_agreement
    zone_overlap = ens["zone_overlap_atr"].replace(-np.inf, np.nan).values
    zone_ok = (~np.isnan(zone_overlap)) & (zone_overlap > 0.0) & (zone_overlap <= p.max_zone_width_atr)
    horizon_med = ens["projected_completion_median"].values
    horizon_ok = np.isnan(horizon_med) | (horizon_med <= p.max_horizon_bars)
    vpin_gate = ens["vpin_gate"].astype(str).fillna("allow").values
    vpin_ok = vpin_gate != "stand_down"
    regime_label = ens["regime_label"].astype(str).fillna("ambiguous").values
    BAD_REGIMES = {"stand_down", "stressed_illiquid", "ambiguous"}
    regime_ok = np.array([r not in BAD_REGIMES for r in regime_label])
    bias = ens["ensemble_bias"].fillna(0).astype(int).values
    bias_ok = bias != 0
    conf = ens["ensemble_confidence"].fillna(0.0).astype(float).values
    conf_ok = conf >= p.min_confidence

    structural_eligible = agree_ok & zone_ok & horizon_ok & vpin_ok & regime_ok & bias_ok & pre_cutoff
    trade_eligible = structural_eligible & conf_ok

    # Optional regime extras (roll_spread_proxy used by `roll_spread` cost model).
    roll_spread_proxy = np.zeros(len(source_df), dtype=float)
    if regime_csv is not None and regime_csv.exists():
        reg = pd.read_csv(regime_csv)
        if len(reg) == len(source_df) and "roll_spread_proxy" in reg.columns:
            roll_spread_proxy = reg["roll_spread_proxy"].fillna(0.0).astype(float).values

    return pd.DataFrame({
        "bias": bias,
        "trade_eligible": trade_eligible,
        "ensemble_confidence": conf,
        "regime_label": regime_label,
        "vpin_gate": vpin_gate,
        "session_phase": np.where(et_hour * 60 + et_min < 10 * 60, "open",
                                  np.where(et_hour * 60 + et_min < 15 * 60, "mid", "close")),
        "roll_spread_proxy": roll_spread_proxy,
        "structural_eligible": structural_eligible,
    })


def trade_eligibility_audit(
    *,
    ensemble_csv: Path,
    source_df: pd.DataFrame,
    latest_entry_time_et: str,
) -> dict:
    """Per-instrument trade-eligibility breakdown reusing the same gates.

    Returns counts of bars passing each individual gate plus joint pass-rate
    at confidence thresholds 0.50 and 0.65. No I/O side effects.
    """
    out = {}
    for thr in (0.50, 0.65):
        sig = recompute_trade_eligibility(
            ensemble_csv=ensemble_csv,
            source_df=source_df,
            params=EligibilityParams(latest_entry_time_et=latest_entry_time_et,
                                       min_confidence=thr),
        )
        out[f"eligible_at_{thr:.2f}"] = int(sig["trade_eligible"].sum())
    return out
