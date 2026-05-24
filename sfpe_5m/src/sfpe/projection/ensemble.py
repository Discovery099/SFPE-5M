"""Ensemble alignment (spec §7.4) + bias override (§7.5) + confidence (§7.6).

All four engine projections are taken as synchronized snapshots at the close of
every source bar t. We never trigger ensemble computation on engine-close events.

This module accepts a list of per-engine projection DataFrames (all with the same
index = source bars) and produces a single ensemble DataFrame with one row per
source bar.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

ENSEMBLE_COLS = [
    "symbol", "timestamp", "session_date",
    "current_price", "current_atr",
    "ensemble_bias", "ensemble_confidence",
    "agreement_count",
    "projected_close_low", "projected_close_mid", "projected_close_high",
    "projected_completion_min", "projected_completion_median", "projected_completion_max",
    "zone_width_atr", "zone_overlap_atr",
    "override_applied", "reason_codes",
    "vpin_gate", "vpin_gate_confidence", "regime_label", "regime_confidence",
    "trade_eligible", "ineligibility_reason",
    "engine_votes",
]


@dataclass
class EnsembleParams:
    min_engines_agree: int = 3
    max_zone_width_atr: float = 1.5     # see BLOCKERS §30
    max_horizon_bars: int = 12          # default; runner overrides per instrument
    override_min_confidence: float = 0.7
    latest_entry_time: str = "15:30"    # default; runner overrides per instrument
    allowed_strategy_for_bias: dict = None


DEFAULT_ALLOWED = {
    # bias direction -> set of regime labels that allow that bias
    1:  {"noise_mean_reverting", "informed_trending", "balanced_or_choppy"},   # long
    -1: {"noise_mean_reverting", "informed_trending", "balanced_or_choppy"},   # short
}


def _interval_intersection(intervals: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Intersection of a list of [low, high] intervals. None if empty."""
    if not intervals:
        return None
    los = [i[0] for i in intervals if pd.notna(i[0])]
    his = [i[1] for i in intervals if pd.notna(i[1])]
    if not los or not his:
        return None
    lo = max(los)
    hi = min(his)
    if lo > hi:
        return None
    return (lo, hi)


def _apply_overrides(
    per_engine_rows: list[dict],
    *,
    absorption_row,
    vacuum_row,
    tpo_row,
    regime_row,
    override_min_confidence: float,
) -> tuple[list[dict], list[str]]:
    """Per spec §7.5. Returns updated per-engine bias list + reason codes."""
    reasons: list[str] = []
    # Absorption at anchor with high confidence → bias AWAY from absorbed level
    if absorption_row is not None and bool(absorption_row.get("absorption_flag", False)):
        ac = float(absorption_row.get("absorption_confidence", 0))
        side = str(absorption_row.get("absorption_side", ""))
        if ac >= override_min_confidence and side in ("bid_absorption", "ask_absorption"):
            new_bias = -1 if side == "bid_absorption" else 1  # bid_abs -> reversal down
            reasons.append(f"override_absorption_{side}")
            for r in per_engine_rows:
                r["bias"] = new_bias
    # Failed-auction override
    if tpo_row is not None and bool(tpo_row.get("failed_auction_flag", False)):
        if float(tpo_row.get("tpo_confidence", 0)) >= override_min_confidence:
            fa_side = int(tpo_row.get("failed_auction_side", 0))
            if fa_side != 0:
                new_bias = -fa_side    # failed_auction_up -> bias down
                reasons.append(f"override_failed_auction_{fa_side:+d}")
                for r in per_engine_rows:
                    r["bias"] = new_bias
    # Vacuum override
    if vacuum_row is not None and bool(vacuum_row.get("vacuum_flag", False)):
        vc = float(vacuum_row.get("vacuum_confidence", 0))
        cls = str(vacuum_row.get("expected_classification", ""))
        if vc >= override_min_confidence and cls == "reversal":
            side = int(vacuum_row.get("vacuum_side", 0))
            new_bias = -side          # snap back
            reasons.append("override_vacuum_reversal")
            for r in per_engine_rows:
                r["bias"] = new_bias
        elif vc >= override_min_confidence and cls == "continuation":
            side = int(vacuum_row.get("vacuum_side", 0))
            reasons.append("override_vacuum_continuation")
            for r in per_engine_rows:
                r["bias"] = side
    return per_engine_rows, reasons


def build_ensemble(
    *,
    symbol: str,
    source_df: pd.DataFrame,
    per_engine: dict[str, pd.DataFrame],
    feature_regime: pd.DataFrame,
    feature_vpin: pd.DataFrame,
    feature_absorption: pd.DataFrame,
    feature_vacuum: pd.DataFrame,
    feature_tpo: pd.DataFrame,
    params: EnsembleParams | None = None,
) -> pd.DataFrame:
    p = params or EnsembleParams()
    n = len(source_df)
    rows = []

    engine_names = list(per_engine.keys())
    n_engines = len(engine_names)

    times = source_df["timestamp"].values
    closes = source_df["close"].values
    atrs = source_df["atr_20"].values
    sds = source_df["session_date"].values

    latest_entry = pd.to_datetime(p.latest_entry_time).time()

    for t in range(n):
        # Gather per-engine projections at this source bar.
        eng_rows = []
        for ename in engine_names:
            row = per_engine[ename].iloc[t].to_dict()
            row["engine"] = ename
            eng_rows.append(row)

        # Pull feature snapshots at bar t.
        abs_row = feature_absorption.iloc[t].to_dict() if feature_absorption is not None and t < len(feature_absorption) else None
        vac_row = feature_vacuum.iloc[t].to_dict() if feature_vacuum is not None and t < len(feature_vacuum) else None
        tpo_row = feature_tpo.iloc[t].to_dict() if feature_tpo is not None and t < len(feature_tpo) else None
        reg_row = feature_regime.iloc[t].to_dict() if feature_regime is not None and t < len(feature_regime) else None
        vp_row = feature_vpin.iloc[t].to_dict() if feature_vpin is not None and t < len(feature_vpin) else None

        # Apply structural bias overrides (spec §7.5).
        eng_rows, override_reasons = _apply_overrides(
            eng_rows,
            absorption_row=abs_row, vacuum_row=vac_row,
            tpo_row=tpo_row, regime_row=reg_row,
            override_min_confidence=p.override_min_confidence,
        )
        override_applied = bool(override_reasons)

        # Agreement (spec §7.4): biases with sign 0 abstain (do not count).
        biases = [int(r.get("bias", 0)) for r in eng_rows]
        votes_up = sum(1 for b in biases if b > 0)
        votes_dn = sum(1 for b in biases if b < 0)
        agreement_count = max(votes_up, votes_dn)
        if agreement_count == 0:
            ensemble_bias = 0
        else:
            ensemble_bias = 1 if votes_up >= votes_dn else -1

        # Zone overlap: intersection of projected_close intervals across all 4 engines.
        intervals = [(r.get("projected_close_low"), r.get("projected_close_high")) for r in eng_rows]
        intersect = _interval_intersection(intervals)
        cur_atr = atrs[t]
        if intersect is None:
            zone_lo = float("nan")
            zone_hi = float("nan")
            zone_overlap_atr = float("-inf")
            zone_width_atr = float("inf")
        else:
            zone_lo, zone_hi = intersect
            zone_overlap_atr = ((zone_hi - zone_lo) / cur_atr) if cur_atr and cur_atr > 0 else float("nan")
            zone_width_atr = zone_overlap_atr

        # ensemble_projected_close = midpoint of agreeing engines' mids
        agreeing = [r for r, b in zip(eng_rows, biases) if (b == ensemble_bias and ensemble_bias != 0)]
        if agreeing:
            mids = [float(r["projected_close_mid"]) for r in agreeing if pd.notna(r["projected_close_mid"])]
            ensemble_close_mid = float(np.mean(mids)) if mids else float("nan")
            ensemble_close_low = float(np.min([float(r["projected_close_low"]) for r in agreeing if pd.notna(r["projected_close_low"])])) if agreeing else float("nan")
            ensemble_close_high = float(np.max([float(r["projected_close_high"]) for r in agreeing if pd.notna(r["projected_close_high"])])) if agreeing else float("nan")
        else:
            ensemble_close_mid = float("nan")
            ensemble_close_low = float("nan")
            ensemble_close_high = float("nan")

        # Completion-window UNION across all 4 engines.  Time projection unions
        # because the realized time-to-close is per-engine (one of the 4 closes
        # at that bar), so the ensemble's "completion window" should cover all
        # plausible engine-close moments. See BLOCKERS §35.
        completion_mins = [r.get("projected_completion_source_bars_min") for r in eng_rows
                           if pd.notna(r.get("projected_completion_source_bars_min"))]
        completion_maxes = [r.get("projected_completion_source_bars_max") for r in eng_rows
                            if pd.notna(r.get("projected_completion_source_bars_max"))]
        completion_meds = [r.get("projected_completion_source_bars_median") for r in eng_rows
                           if pd.notna(r.get("projected_completion_source_bars_median"))]
        if completion_mins and completion_maxes:
            comp_min = float(min(completion_mins))
            comp_max = float(max(completion_maxes))
            comp_med = float(np.median(completion_meds)) if completion_meds else float("nan")
        else:
            comp_min = float("nan")
            comp_max = float("nan")
            comp_med = float("nan")

        # ensemble_confidence (spec §7.6, GEOMETRIC MEAN of the 5 factors).
        # See BLOCKERS §29 for why we use geo-mean rather than raw product.
        agree_term = agreement_count / float(n_engines)
        if zone_width_atr is None or np.isinf(zone_width_atr) or np.isnan(zone_width_atr):
            zone_term = 0.0
        else:
            zone_term = max(0.0, 1.0 - (zone_width_atr / p.max_zone_width_atr))
            zone_term = min(zone_term, 1.0)
        if agreeing:
            mean_conf_agree = float(np.mean([float(r["confidence"]) for r in agreeing]))
        else:
            mean_conf_agree = 0.0
        vpin_gate = str(vp_row.get("gate_decision", "allow")) if vp_row else "allow"
        vpin_gate_conf = float(vp_row.get("gate_confidence", 1.0)) if vp_row else 1.0
        regime_label = str(reg_row.get("regime_label", "ambiguous")) if reg_row else "ambiguous"
        regime_conf = float(reg_row.get("regime_confidence", 0.0)) if reg_row else 0.0
        # Geometric mean: any zero factor zeros out the result.
        factors = [agree_term, zone_term, mean_conf_agree, vpin_gate_conf, regime_conf]
        if any(f <= 0.0 for f in factors):
            ensemble_conf = 0.0
        else:
            ensemble_conf = float(np.prod(factors) ** (1.0 / len(factors)))
        ensemble_conf = max(0.0, min(1.0, ensemble_conf))

        # Trade eligibility (spec §7.4).
        ineligibility = []
        if agreement_count < p.min_engines_agree:
            ineligibility.append(f"agreement_{agreement_count}")
        if zone_overlap_atr == float("-inf"):
            ineligibility.append("no_zone_overlap")
        elif zone_overlap_atr > p.max_zone_width_atr:
            ineligibility.append("zone_too_wide")
        if not np.isnan(comp_med) and comp_med > p.max_horizon_bars:
            ineligibility.append("horizon_too_long")
        if vpin_gate == "stand_down":
            ineligibility.append("vpin_toxic")
        if regime_label in ("stand_down", "stressed_illiquid", "ambiguous"):
            ineligibility.append(f"regime_{regime_label}")
        cur_time = pd.Timestamp(times[t]).time()
        if cur_time >= latest_entry:
            ineligibility.append("past_latest_entry")
        trade_eligible = (len(ineligibility) == 0 and ensemble_bias != 0)

        # engine votes dict for output
        votes = {
            ename: {"bias": int(eng_rows[i].get("bias", 0)),
                    "confidence": float(eng_rows[i].get("confidence", 0))}
            for i, ename in enumerate(engine_names)
        }

        rows.append({
            "symbol": symbol,
            "timestamp": pd.Timestamp(times[t]),
            "session_date": sds[t],
            "current_price": float(closes[t]),
            "current_atr": float(cur_atr) if pd.notna(cur_atr) else float("nan"),
            "ensemble_bias": int(ensemble_bias),
            "ensemble_confidence": float(ensemble_conf),
            "agreement_count": int(agreement_count),
            "projected_close_low": ensemble_close_low,
            "projected_close_mid": ensemble_close_mid,
            "projected_close_high": ensemble_close_high,
            "projected_completion_min": comp_min,
            "projected_completion_median": comp_med,
            "projected_completion_max": comp_max,
            "zone_width_atr": float(zone_width_atr) if (zone_width_atr is not None and not np.isinf(zone_width_atr)) else float("nan"),
            "zone_overlap_atr": float(zone_overlap_atr) if zone_overlap_atr is not None and not np.isinf(zone_overlap_atr) else float("-inf") if zone_overlap_atr == float("-inf") else float("nan"),
            "override_applied": override_applied,
            "reason_codes": ";".join(override_reasons) if override_reasons else "",
            "vpin_gate": vpin_gate,
            "vpin_gate_confidence": vpin_gate_conf,
            "regime_label": regime_label,
            "regime_confidence": regime_conf,
            "trade_eligible": trade_eligible,
            "ineligibility_reason": ";".join(ineligibility),
            "engine_votes": str(votes),
        })
    out = pd.DataFrame(rows, columns=ENSEMBLE_COLS)
    return out
