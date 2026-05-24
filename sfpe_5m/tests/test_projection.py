"""Spec §7 projection schema + sanity tests (fast subset)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.data.calendar import load_calendars  # noqa: E402
from sfpe.data.loader import load_instrument_csv  # noqa: E402
from sfpe.data.families import target_bars_for_family  # noqa: E402
from sfpe.projection.engine_state import (  # noqa: E402
    vol_budget_trace, dollar_imbalance_trace,
    volume_time_trace, range_budget_trace, STATE_COLS,
)
from sfpe.projection.per_engine import project_engine, PROJECTION_COLS  # noqa: E402
from sfpe.projection.ensemble import build_ensemble, ENSEMBLE_COLS, EnsembleParams  # noqa: E402
from sfpe.features.absorption import compute_absorption  # noqa: E402
from sfpe.features.liquidity_vacuum import compute_vacuum  # noqa: E402
from sfpe.features.regime_router import compute_regime  # noqa: E402
from sfpe.features.vpin_proxy import compute_vpin  # noqa: E402
from sfpe.features.tpo_profile import compute_tpo  # noqa: E402

ES_CSV = REPO / "data" / "raw" / "ES_5min_RTH_6year.csv"


@pytest.fixture(scope="module")
def es_loaded_slice():
    """Use a smallish slice (10k bars) for schema tests so this stays fast."""
    if not ES_CSV.exists():
        pytest.skip(f"ES CSV not found at {ES_CSV}")
    cals = load_calendars(REPO / "config" / "session_calendars.yaml")
    df = load_instrument_csv(ES_CSV, cals["RTH_eq"])
    return df.iloc[:10000].reset_index(drop=True).copy()


def test_engine_state_schemas(es_loaded_slice):
    df = es_loaded_slice
    target = target_bars_for_family("sp500")
    for trace_fn, kwargs in [
        (vol_budget_trace, dict(target_bars_per_session=target)),
        (dollar_imbalance_trace, dict(point_value=50.0,
                                       target_bars_per_session=target,
                                       expected_bars_per_session=78)),
        (volume_time_trace, dict(target_bars_per_session=target)),
        (range_budget_trace, dict(range_k=1.5)),
    ]:
        out = trace_fn(df, symbol="ES", **kwargs)
        missing = set(STATE_COLS) - set(out.columns)
        assert not missing, f"{trace_fn.__name__} missing cols: {missing}"
        assert len(out) == len(df)


def test_per_engine_projection_schema(es_loaded_slice):
    df = es_loaded_slice
    state = vol_budget_trace(df, symbol="ES",
                              target_bars_per_session=target_bars_for_family("sp500"),
                              variance_lookback_sessions=20)
    proj = project_engine(engine_name="vol_budget", state=state, source_df=df)
    missing = set(PROJECTION_COLS) - set(proj.columns)
    assert not missing, f"projection missing cols: {missing}"
    assert len(proj) == len(df)
    # Bias is in {-1, 0, 1}
    assert set(proj["bias"].dropna().unique()).issubset({-1, 0, 1})
    # Confidence is in [0, 1]
    assert ((proj["confidence"] >= 0) & (proj["confidence"] <= 1)).all()


def test_ensemble_schema_and_eligibility(es_loaded_slice):
    df = es_loaded_slice
    a = compute_absorption(df, family="sp500", tick_size=0.25)
    v = compute_vacuum(df, family="sp500")
    r = compute_regime(df)
    vp = compute_vpin(df, tick_size=0.25)
    tpo = compute_tpo(df, tick_size=0.25)
    state_vb = vol_budget_trace(df, symbol="ES",
                                 target_bars_per_session=target_bars_for_family("sp500"),
                                 variance_lookback_sessions=20)
    state_di = dollar_imbalance_trace(df, symbol="ES", point_value=50.0,
                                       target_bars_per_session=target_bars_for_family("sp500"),
                                       expected_bars_per_session=78)
    state_vt = volume_time_trace(df, symbol="ES",
                                  target_bars_per_session=target_bars_for_family("sp500"))
    state_rb = range_budget_trace(df, symbol="ES", range_k=1.5)
    proj_vb = project_engine(engine_name="vol_budget", state=state_vb, source_df=df)
    proj_di = project_engine(engine_name="dollar_imbalance", state=state_di, source_df=df)
    proj_vt = project_engine(engine_name="volume_time", state=state_vt, source_df=df)
    proj_rb = project_engine(engine_name="range_budget", state=state_rb, source_df=df)
    ens = build_ensemble(
        symbol="ES", source_df=df,
        per_engine={"vol_budget": proj_vb, "dollar_imbalance": proj_di,
                    "volume_time": proj_vt, "range_budget": proj_rb},
        feature_regime=r, feature_vpin=vp, feature_absorption=a,
        feature_vacuum=v, feature_tpo=tpo,
        params=EnsembleParams(min_engines_agree=3, max_zone_width_atr=1.5,
                              max_horizon_bars=12, override_min_confidence=0.7,
                              latest_entry_time="15:30"),
    )
    missing = set(ENSEMBLE_COLS) - set(ens.columns)
    assert not missing, f"ensemble missing cols: {missing}"
    assert len(ens) == len(df)
    # ensemble_bias in {-1, 0, 1}
    assert set(ens["ensemble_bias"].unique()).issubset({-1, 0, 1})
    # ensemble_confidence in [0, 1]
    assert ((ens["ensemble_confidence"] >= 0) & (ens["ensemble_confidence"] <= 1)).all()
    # agreement_count in {0..4}
    assert set(ens["agreement_count"].unique()).issubset({0, 1, 2, 3, 4})
    # trade_eligible is bool
    assert ens["trade_eligible"].dtype == bool
