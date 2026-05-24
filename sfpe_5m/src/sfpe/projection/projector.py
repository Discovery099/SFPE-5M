"""Top-level projection orchestrator (spec §7).

For one instrument:
  1. load source bars + all 6 features + all 4 engine state traces + 4 magnitude_projection CSVs
  2. run per-engine projection on each engine state trace
  3. build ensemble via the spec §7.4 alignment rule
  4. return + persist ensemble CSV + per-engine projection CSVs
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import yaml
from loguru import logger

from sfpe.data.calendar import load_calendars
from sfpe.data.loader import load_instrument_csv
from sfpe.data.families import target_bars_for_family, asset_class_of
from sfpe.features.absorption import compute_absorption
from sfpe.features.liquidity_vacuum import compute_vacuum
from sfpe.features.regime_router import compute_regime
from sfpe.features.vpin_proxy import compute_vpin
from sfpe.features.tpo_profile import compute_tpo
from sfpe.features.magnitude_projection import compute_magnitude_projection
from sfpe.synthetic.vol_budget import VolBudgetEngine
from sfpe.synthetic.dollar_imbalance import DollarImbalanceEngine
from sfpe.synthetic.volume_time import VolumeTimeEngine
from sfpe.synthetic.range_budget import RangeBudgetEngine
from sfpe.synthetic.base import bars_to_dataframe
from sfpe.projection.engine_state import (
    vol_budget_trace, dollar_imbalance_trace,
    volume_time_trace, range_budget_trace,
)
from sfpe.projection.per_engine import project_engine, ProjectionParams
from sfpe.projection.ensemble import build_ensemble, EnsembleParams

RANGE_K_BY_FAMILY = {"equity": 1.5, "commodity": 1.5}


def _run_engine_bars(engine_name: str, df: pd.DataFrame, sym: str, ic: dict, cal) -> pd.DataFrame:
    family = ic["family"]
    asset_class = asset_class_of(family)
    target_bars = target_bars_for_family(family)
    engines = {
        "vol_budget": VolBudgetEngine,
        "dollar_imbalance": DollarImbalanceEngine,
        "volume_time": VolumeTimeEngine,
        "range_budget": RangeBudgetEngine,
    }
    engine = engines[engine_name]()
    if engine_name == "vol_budget":
        bars = engine.run(df, symbol=sym, target_bars_per_session=target_bars,
                          variance_lookback_sessions=20, sigma_mult=1.0,
                          variance_proxy="parkinson",
                          min_source_bars=1, max_source_bars=cal.expected_bars)
    elif engine_name == "dollar_imbalance":
        bars = engine.run(df, symbol=sym, point_value=float(ic["point_value"]),
                          imbalance_window=50, theta_mult=1.0,
                          target_bars_per_session=target_bars,
                          expected_bars_per_session=cal.expected_bars,
                          min_source_bars=1, max_source_bars=cal.expected_bars)
    elif engine_name == "volume_time":
        bars = engine.run(df, symbol=sym, target_bars_per_session=target_bars,
                          session_volume_lookback=20,
                          min_source_bars=1, max_source_bars=cal.expected_bars)
    else:
        bars = engine.run(df, symbol=sym, range_k=RANGE_K_BY_FAMILY[asset_class],
                          min_source_bars=1, max_source_bars=cal.expected_bars)
    return bars_to_dataframe(bars)


def _engine_state_trace(engine_name: str, df: pd.DataFrame, sym: str, ic: dict, cal) -> pd.DataFrame:
    family = ic["family"]
    target_bars = target_bars_for_family(family)
    if engine_name == "vol_budget":
        return vol_budget_trace(
            df, symbol=sym, target_bars_per_session=target_bars,
            variance_lookback_sessions=20, sigma_mult=1.0,
            min_source_bars=1, max_source_bars=cal.expected_bars,
        )
    if engine_name == "dollar_imbalance":
        return dollar_imbalance_trace(
            df, symbol=sym, point_value=float(ic["point_value"]),
            imbalance_window=50, theta_mult=1.0,
            target_bars_per_session=target_bars,
            expected_bars_per_session=cal.expected_bars,
            min_source_bars=1, max_source_bars=cal.expected_bars,
        )
    if engine_name == "volume_time":
        return volume_time_trace(
            df, symbol=sym, target_bars_per_session=target_bars,
            session_volume_lookback=20,
            min_source_bars=1, max_source_bars=cal.expected_bars,
        )
    return range_budget_trace(
        df, symbol=sym, range_k=RANGE_K_BY_FAMILY[asset_class_of(family)],
        min_source_bars=1, max_source_bars=cal.expected_bars,
    )


def build_projections_for_symbol(
    symbol: str,
    *,
    repo_root: Path,
    write_outputs: bool = True,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Returns (ensemble_df, per_engine_dict)."""
    cfg = yaml.safe_load((repo_root / "config" / "instruments.yaml").read_text())
    cals = load_calendars(repo_root / "config" / "session_calendars.yaml")
    ic = cfg["instruments"][symbol]
    cal = cals[ic["calendar"]]
    family = ic["family"]
    tick = float(ic["tick_size"])

    df = load_instrument_csv(repo_root / ic["file"], cal)

    # Features
    a = compute_absorption(df, family=family, tick_size=tick)
    v = compute_vacuum(df, family=family)
    r = compute_regime(df)
    vp = compute_vpin(df, tick_size=tick)
    tpo = compute_tpo(df, tick_size=tick)

    per_engine: dict[str, pd.DataFrame] = {}
    for ename in ["vol_budget", "dollar_imbalance", "volume_time", "range_budget"]:
        state = _engine_state_trace(ename, df, symbol, ic, cal)
        # magnitude_projection requires the engine's completed synth bars + all features.
        completed = _run_engine_bars(ename, df, symbol, ic, cal)
        mag = compute_magnitude_projection(
            completed, source_df=df, feature_regime=r, feature_vpin=vp,
            feature_absorption=a, feature_vacuum=v, feature_tpo=tpo,
            expected_bars_per_session=cal.expected_bars,
        )
        # Attach start_idx as the join key
        mag_with_idx = pd.concat(
            [completed.reset_index(drop=True)[["start_idx"]],
             mag.reset_index(drop=True)],
            axis=1,
        )
        proj = project_engine(
            engine_name=ename, state=state, source_df=df,
            magnitude_df=mag_with_idx,
        )
        per_engine[ename] = proj

    # Per-instrument ensemble params (latest_entry_time from instruments.yaml)
    ens_params = EnsembleParams(
        min_engines_agree=3,
        max_zone_width_atr=1.5,
        max_horizon_bars=max(8, cal.expected_bars // 6),  # ~13 for ES, 10 for MGC, 11 for MCL
        override_min_confidence=0.7,
        latest_entry_time=ic["latest_entry_time"],
    )
    ensemble = build_ensemble(
        symbol=symbol, source_df=df, per_engine=per_engine,
        feature_regime=r, feature_vpin=vp, feature_absorption=a,
        feature_vacuum=v, feature_tpo=tpo, params=ens_params,
    )

    if write_outputs:
        out_dir = repo_root / "features"
        out_dir.mkdir(parents=True, exist_ok=True)
        ensemble.to_csv(out_dir / f"projection_ensemble__{symbol}.csv", index=False)
        for ename, edf in per_engine.items():
            edf.to_csv(out_dir / f"projection_engine__{ename}__{symbol}.csv", index=False)

    return ensemble, per_engine
