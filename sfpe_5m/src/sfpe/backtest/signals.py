"""Phase 5 signal generation utilities (v1.5 — projection-aware exits).

The Phase-4 ensemble CSV (`features/projection_ensemble__<SYM>.csv`) has a
broken `trade_eligible` column (BLOCKERS §38 — UTC vs ET timestamp bug). This
module recomputes per-bar trade eligibility from the underlying gate columns
plus a properly tz-aware source timestamp + a confidence threshold.

**Phase 5.5 upgrade (2026-05-24):** also passes through the projection envelope
(`projected_close_low/mid/high`, `projected_completion_median`) AND derives
the structural stop level per spec §8.3 by merging the absorption/vacuum/TPO
feature CSVs. The engine consumes these to use projection-derived TP1/TP2 and
structural stops INSTEAD of generic ATR-multiplier exits.

Outputs a per-source-bar DataFrame aligned 1:1 with the source loader frame,
providing the inputs the EventEngine expects.
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
    latest_entry_time_et: str = "15:30"
    min_confidence: float = 0.65


@dataclass
class StructuralStopParams:
    """Spec §8.3 stop construction.

    structural_buffer_atr_mult: anchor ± mult × ATR_20 (default 0.5).
    fallback_buffer_atr_mult: when no structural override, fallback to
       synthetic-open ± mult × ATR_20 (default 0.5).
    """
    structural_buffer_atr_mult: float = 0.5
    fallback_buffer_atr_mult: float = 0.5


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def derive_structural_stops(
    *,
    reason_codes: np.ndarray,
    atr_20: np.ndarray,
    absorption_level: np.ndarray,
    vacuum_extreme: np.ndarray,
    vacuum_origin: np.ndarray,
    tpo_target: np.ndarray,
    buffer_atr_mult: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per spec §8.3, derive structural stop levels from reason_codes.

    Priority order (when multiple overrides coexist): absorption >
    failed_auction > vacuum_continuation > vacuum_reversal.

    Returns:
        structural_stop_long:  np.array, NaN where no override or anchor missing
        structural_stop_short: np.array, NaN where no override or anchor missing
        has_structural_stop:   bool array, True where stop is finite-valued
    """
    n = len(reason_codes)
    # Vectorised override-kind detection.
    is_abs = np.array([("override_absorption" in (r or "")) for r in reason_codes])
    is_vc = np.array([("override_vacuum_continuation" in (r or "")) for r in reason_codes])
    is_vr = np.array([("override_vacuum_reversal" in (r or "")) for r in reason_codes])
    is_fa = np.array([("override_failed_auction" in (r or "")) for r in reason_codes])

    # Anchor selection by priority (later writes overwrite earlier).
    anchor = np.full(n, np.nan, dtype=float)
    anchor[is_vr] = vacuum_origin[is_vr]
    anchor[is_vc] = vacuum_extreme[is_vc]
    anchor[is_fa] = tpo_target[is_fa]
    anchor[is_abs] = absorption_level[is_abs]

    buf = buffer_atr_mult * atr_20
    structural_stop_long = anchor - buf
    structural_stop_short = anchor + buf
    has_structural_stop = np.isfinite(structural_stop_long) & np.isfinite(structural_stop_short)
    return structural_stop_long, structural_stop_short, has_structural_stop


def recompute_trade_eligibility(
    *,
    ensemble_csv: Path,
    source_df: pd.DataFrame,
    regime_csv: Optional[Path] = None,
    params: Optional[EligibilityParams] = None,
    # NEW v1.5 inputs — passing these enables projection-aware exits in the
    # downstream engine.  All four CSVs must be row-aligned with source_df.
    absorption_csv: Optional[Path] = None,
    vacuum_csv: Optional[Path] = None,
    tpo_csv: Optional[Path] = None,
    structural_stop_params: Optional[StructuralStopParams] = None,
) -> pd.DataFrame:
    """Return a per-bar signal frame for the EventEngine.

    `source_df` must be the OUTPUT of `loader.load_instrument_csv()` — it has
    a tz-aware `timestamp` column in `America/New_York`. The ensemble CSV has
    naive UTC timestamps; we align by row position (both are aligned 1:1 with
    the source bar sequence).
    """
    p = params or EligibilityParams()
    sp = structural_stop_params or StructuralStopParams()
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

    # Regime extras (roll_spread_proxy used by `roll_spread` cost model).
    roll_spread_proxy = np.zeros(len(source_df), dtype=float)
    if regime_csv is not None and regime_csv.exists():
        reg = pd.read_csv(regime_csv)
        if len(reg) == len(source_df) and "roll_spread_proxy" in reg.columns:
            roll_spread_proxy = reg["roll_spread_proxy"].fillna(0.0).astype(float).values

    # Projection passthrough — TP1 / TP2 anchors + time-stop driver.  When the
    # ensemble CSV is missing these (e.g. older Phase-4 snapshots, unit-test
    # stubs), default to NaN so the engine falls through to the legacy ATR path.
    def _opt(col: str, dtype=float) -> np.ndarray:
        return (ens[col].astype(dtype).values
                if col in ens.columns
                else np.full(len(source_df), np.nan, dtype=float))

    proj_close_low = _opt("projected_close_low")
    proj_close_mid = _opt("projected_close_mid")
    proj_close_high = _opt("projected_close_high")
    proj_completion_median = _opt("projected_completion_median")
    reason_codes = (ens["reason_codes"].fillna("").astype(str).values
                    if "reason_codes" in ens.columns
                    else np.array([""] * len(source_df), dtype=object))
    current_price = (ens["current_price"].astype(float).values
                     if "current_price" in ens.columns
                     else source_df["close"].astype(float).values)

    out_dict = dict(
        bias=bias,
        trade_eligible=trade_eligible,
        ensemble_confidence=conf,
        regime_label=regime_label,
        vpin_gate=vpin_gate,
        session_phase=np.where(et_hour * 60 + et_min < 10 * 60, "open",
                                np.where(et_hour * 60 + et_min < 15 * 60, "mid", "close")),
        roll_spread_proxy=roll_spread_proxy,
        structural_eligible=structural_eligible,
        # v1.5 projection passthrough
        projected_close_low=proj_close_low,
        projected_close_mid=proj_close_mid,
        projected_close_high=proj_close_high,
        projected_completion_median=proj_completion_median,
        reason_codes=reason_codes,
        current_price=current_price,
        # synthetic-open fallback anchor: signal-bar's source open (causal).
        synthetic_open_anchor=source_df["open"].astype(float).values,
    )

    # v1.5 structural stop derivation. If feature CSVs are not provided we
    # leave structural_stop_* as NaN and the engine will fall back to the
    # synthetic-open ± fallback_buffer × ATR rule for every bar.
    n = len(source_df)
    stop_long = np.full(n, np.nan, dtype=float)
    stop_short = np.full(n, np.nan, dtype=float)
    has_struct = np.zeros(n, dtype=bool)
    if absorption_csv is not None and vacuum_csv is not None and tpo_csv is not None:
        abs_df = pd.read_csv(absorption_csv)
        vac_df = pd.read_csv(vacuum_csv)
        tpo_df = pd.read_csv(tpo_csv)
        for name, df in (("absorption", abs_df), ("vacuum", vac_df), ("tpo", tpo_df)):
            if len(df) != n:
                raise ValueError(
                    f"{name} CSV row count {len(df):,} != source row count "
                    f"{n:,}; alignment broken"
                )
        stop_long, stop_short, has_struct = derive_structural_stops(
            reason_codes=reason_codes,
            atr_20=source_df["atr_20"].astype(float).values,
            absorption_level=abs_df["absorption_level"].astype(float).values,
            vacuum_extreme=vac_df["extreme_level"].astype(float).values,
            vacuum_origin=vac_df["origin_level"].astype(float).values,
            tpo_target=tpo_df["target_level"].astype(float).values,
            buffer_atr_mult=sp.structural_buffer_atr_mult,
        )
    out_dict["structural_stop_long"] = stop_long
    out_dict["structural_stop_short"] = stop_short
    out_dict["has_structural_stop"] = has_struct

    return pd.DataFrame(out_dict)


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
