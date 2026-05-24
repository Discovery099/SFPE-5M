"""Spec §6 ideas 5-10 feature schema & sanity tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.data.calendar import load_calendars  # noqa: E402
from sfpe.data.loader import load_instrument_csv  # noqa: E402
from sfpe.features.absorption import compute_absorption  # noqa: E402
from sfpe.features.liquidity_vacuum import compute_vacuum  # noqa: E402
from sfpe.features.regime_router import compute_regime  # noqa: E402
from sfpe.features.vpin_proxy import compute_vpin  # noqa: E402
from sfpe.features.tpo_profile import compute_tpo  # noqa: E402
from sfpe.features.magnitude_projection import compute_magnitude_projection  # noqa: E402
from sfpe.synthetic.vol_budget import VolBudgetEngine  # noqa: E402
from sfpe.synthetic.base import bars_to_dataframe  # noqa: E402

ES_CSV = REPO / "data" / "raw" / "ES_5min_RTH_6year.csv"


@pytest.fixture(scope="module")
def es_loaded() -> pd.DataFrame:
    if not ES_CSV.exists():
        pytest.skip(f"ES CSV not found at {ES_CSV}")
    cals = load_calendars(REPO / "config" / "session_calendars.yaml")
    return load_instrument_csv(ES_CSV, cals["RTH_eq"])


# -----------------------------------------------------------------------------
# Schema tests (spec §6 ideas 5–10 - exact field names)
# -----------------------------------------------------------------------------

ABSORPTION_SCHEMA = {
    "absorption_flag", "absorption_side", "anchor_type", "absorption_level",
    "expected_reversal_zone_low", "expected_reversal_zone_high", "absorption_confidence",
}
VACUUM_SCHEMA = {
    "vacuum_flag", "vacuum_side", "origin_level", "extreme_level",
    "expected_snap_back_zone_low", "expected_snap_back_zone_high",
    "expected_classification", "vacuum_confidence", "realized_classification",
}
REGIME_SCHEMA = {
    "roll_spread_proxy", "variance_ratio", "spread_percentile", "vr_percentile",
    "regime_label", "regime_confidence", "allowed_strategy_family",
}
VPIN_SCHEMA = {
    "vpin_proxy", "toxicity_percentile", "toxicity_regime",
    "gate_decision", "gate_confidence",
}
TPO_SCHEMA = {
    "VAH_prior", "VAL_prior", "POC_prior", "value_midpoint_prior",
    "failed_auction_flag", "failed_auction_side", "target_level", "tpo_confidence",
}
MAGNITUDE_SCHEMA = {
    "expected_abs_return_q20", "expected_abs_return_q50", "expected_abs_return_q80",
    "expected_range_q20", "expected_range_q50", "expected_range_q80",
    "expected_duration_q20", "expected_duration_q50", "expected_duration_q80",
    "state_confidence", "pooling_level", "stress_flag",
}


def test_absorption_schema(es_loaded):
    a = compute_absorption(es_loaded, family="sp500", tick_size=0.25)
    missing = ABSORPTION_SCHEMA - set(a.columns)
    assert not missing, f"absorption missing: {missing}"
    assert a["absorption_flag"].dtype == bool
    assert a["absorption_flag"].sum() > 50, "too few absorption flags over 5+ years"


def test_vacuum_schema(es_loaded):
    v = compute_vacuum(es_loaded, family="sp500")
    missing = VACUUM_SCHEMA - set(v.columns)
    assert not missing, f"vacuum missing: {missing}"
    assert v["vacuum_flag"].dtype == bool
    assert v["vacuum_flag"].sum() > 50


def test_regime_schema(es_loaded):
    r = compute_regime(es_loaded)
    missing = REGIME_SCHEMA - set(r.columns)
    assert not missing, f"regime missing: {missing}"
    valid = {"noise_mean_reverting", "informed_trending", "stressed_illiquid",
             "balanced_or_choppy", "ambiguous", "stand_down"}
    assert set(r["regime_label"].unique()).issubset(valid)


def test_vpin_schema(es_loaded):
    vp = compute_vpin(es_loaded, tick_size=0.25)
    missing = VPIN_SCHEMA - set(vp.columns)
    assert not missing, f"vpin missing: {missing}"
    valid_regime = {"normal", "elevated", "toxic"}
    valid_gate = {"allow", "half_size", "stand_down"}
    assert set(vp["toxicity_regime"].unique()).issubset(valid_regime)
    assert set(vp["gate_decision"].unique()).issubset(valid_gate)
    # vpin in [0, 1] where defined
    defined = vp["vpin_proxy"].dropna()
    assert ((defined >= 0) & (defined <= 1)).all()


def test_tpo_schema(es_loaded):
    tpo = compute_tpo(es_loaded, tick_size=0.25)
    missing = TPO_SCHEMA - set(tpo.columns)
    assert not missing, f"tpo missing: {missing}"
    assert tpo["VAH_prior"].notna().sum() > 1000
    assert set(tpo["failed_auction_side"].unique()).issubset({-1, 0, 1})


def test_magnitude_projection_schema(es_loaded):
    a = compute_absorption(es_loaded, family="sp500", tick_size=0.25)
    v = compute_vacuum(es_loaded, family="sp500")
    r = compute_regime(es_loaded)
    vp = compute_vpin(es_loaded, tick_size=0.25)
    tpo = compute_tpo(es_loaded, tick_size=0.25)
    bars = VolBudgetEngine().run(
        es_loaded, symbol="ES", target_bars_per_session=18,
        variance_lookback_sessions=20, sigma_mult=1.0,
        variance_proxy="parkinson", min_source_bars=1, max_source_bars=78,
    )
    bdf = bars_to_dataframe(bars)
    mp = compute_magnitude_projection(
        bdf, source_df=es_loaded, feature_regime=r, feature_vpin=vp,
        feature_absorption=a, feature_vacuum=v, feature_tpo=tpo,
        expected_bars_per_session=78,
    )
    missing = MAGNITUDE_SCHEMA - set(mp.columns)
    assert not missing, f"magnitude_projection missing: {missing}"
    # most rows should get a non-default state_confidence
    assert (mp["state_confidence"] > 0).sum() > 0.8 * len(mp)
    # pooling_level distribution
    assert mp["pooling_level"].max() >= 0
