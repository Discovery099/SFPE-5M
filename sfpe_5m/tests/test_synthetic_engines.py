"""Spec §6 (all four engines) — quality-gate tests under the v1.1 corrected
spec amendments (per-family bands + combined autocorr rule).

See BLOCKERS.md §12 (Amendment 2) and §13 (Amendment 1).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.data.calendar import load_calendars  # noqa: E402
from sfpe.data.loader import load_instrument_csv  # noqa: E402
from sfpe.data.families import band_for_family, autocorr_gate, target_bars_for_family  # noqa: E402
from sfpe.synthetic.base import bars_to_dataframe  # noqa: E402
from sfpe.synthetic.vol_budget import VolBudgetEngine  # noqa: E402
from sfpe.synthetic.dollar_imbalance import DollarImbalanceEngine  # noqa: E402
from sfpe.synthetic.volume_time import VolumeTimeEngine  # noqa: E402
from sfpe.synthetic.range_budget import RangeBudgetEngine  # noqa: E402

ES_CSV = REPO / "data" / "raw" / "ES_5min_RTH_6year.csv"
MGC_CSV = REPO / "data" / "raw" / "MGC_5min_RTH_6year.csv"


@pytest.fixture(scope="module")
def es_loaded() -> pd.DataFrame:
    if not ES_CSV.exists():
        pytest.skip(f"ES CSV not found at {ES_CSV}")
    cals = load_calendars(REPO / "config" / "session_calendars.yaml")
    return load_instrument_csv(ES_CSV, cals["RTH_eq"])


@pytest.fixture(scope="module")
def mgc_loaded() -> pd.DataFrame:
    if not MGC_CSV.exists():
        pytest.skip(f"MGC CSV not found at {MGC_CSV}")
    cals = load_calendars(REPO / "config" / "session_calendars.yaml")
    return load_instrument_csv(MGC_CSV, cals["RTH_comex"])


def _ac1(series: pd.Series) -> float:
    vals = series.dropna().values
    if len(vals) < 6:
        return 0.0
    return float(np.corrcoef(vals[:-1], vals[1:])[0, 1])


def _evaluate_engine(loaded_df: pd.DataFrame, bars_df: pd.DataFrame, family: str) -> tuple[bool, str]:
    band_lo, band_hi = band_for_family(family)
    avg = bars_df.groupby("session_date").size().mean()
    in_band = band_lo <= avg <= band_hi
    src_ac1 = _ac1(loaded_df["log_return"])
    synth_ac1 = _ac1(bars_df["log_return"])
    ac_ok, ac_reason = autocorr_gate(synth_ac1, src_ac1)
    return (in_band and ac_ok), (
        f"avg={avg:.2f} band=[{band_lo},{band_hi}] in_band={in_band} | ac: {ac_reason}"
    )


# ============================================================================
# Engine C  vol_budget
# ============================================================================

def test_vol_budget_es_passes_gates(es_loaded):
    bars = VolBudgetEngine().run(
        es_loaded, symbol="ES",
        target_bars_per_session=target_bars_for_family("sp500"),
        variance_lookback_sessions=20,
        sigma_mult=1.0,
        min_source_bars=1,
        max_source_bars=78,
    )
    bdf = bars_to_dataframe(bars)
    assert len(bdf) > 1000
    ok, msg = _evaluate_engine(es_loaded, bdf, family="sp500")
    assert ok, f"vol_budget ES failed: {msg}"


def test_vol_budget_mgc_passes_gates(mgc_loaded):
    bars = VolBudgetEngine().run(
        mgc_loaded, symbol="MGC",
        target_bars_per_session=target_bars_for_family("gold"),
        variance_lookback_sessions=20,
        sigma_mult=1.0,
        min_source_bars=1,
        max_source_bars=60,
    )
    bdf = bars_to_dataframe(bars)
    assert len(bdf) > 500
    ok, msg = _evaluate_engine(mgc_loaded, bdf, family="gold")
    assert ok, f"vol_budget MGC failed: {msg}"


# ============================================================================
# Engine A  dollar_imbalance
# ============================================================================

def test_dollar_imbalance_es_passes_gates(es_loaded):
    bars = DollarImbalanceEngine().run(
        es_loaded, symbol="ES",
        point_value=50.0,
        imbalance_window=50,
        theta_mult=1.0,
        target_bars_per_session=target_bars_for_family("sp500"),
        expected_bars_per_session=78,
    )
    bdf = bars_to_dataframe(bars)
    assert len(bdf) > 1000
    ok, msg = _evaluate_engine(es_loaded, bdf, family="sp500")
    assert ok, f"dollar_imbalance ES failed: {msg}"


def test_dollar_imbalance_mgc_passes_gates(mgc_loaded):
    bars = DollarImbalanceEngine().run(
        mgc_loaded, symbol="MGC",
        point_value=10.0,
        imbalance_window=50,
        theta_mult=1.0,
        target_bars_per_session=target_bars_for_family("gold"),
        expected_bars_per_session=60,
    )
    bdf = bars_to_dataframe(bars)
    assert len(bdf) > 500
    ok, msg = _evaluate_engine(mgc_loaded, bdf, family="gold")
    assert ok, f"dollar_imbalance MGC failed: {msg}"


# ============================================================================
# Engine B  volume_time   (NEW in v1.1)
# ============================================================================

def test_volume_time_es_passes_gates(es_loaded):
    bars = VolumeTimeEngine().run(
        es_loaded, symbol="ES",
        target_bars_per_session=target_bars_for_family("sp500"),
        session_volume_lookback=20,
    )
    bdf = bars_to_dataframe(bars)
    assert len(bdf) > 1000
    ok, msg = _evaluate_engine(es_loaded, bdf, family="sp500")
    assert ok, f"volume_time ES failed: {msg}"


def test_volume_time_mgc_passes_gates(mgc_loaded):
    bars = VolumeTimeEngine().run(
        mgc_loaded, symbol="MGC",
        target_bars_per_session=target_bars_for_family("gold"),
        session_volume_lookback=20,
    )
    bdf = bars_to_dataframe(bars)
    assert len(bdf) > 500
    ok, msg = _evaluate_engine(mgc_loaded, bdf, family="gold")
    assert ok, f"volume_time MGC failed: {msg}"


# ============================================================================
# Engine D  range_budget   (NEW in v1.1)
# ============================================================================

def test_range_budget_es_passes_gates(es_loaded):
    bars = RangeBudgetEngine().run(
        es_loaded, symbol="ES",
        range_k=1.5,
    )
    bdf = bars_to_dataframe(bars)
    assert len(bdf) > 1000
    ok, msg = _evaluate_engine(es_loaded, bdf, family="sp500")
    assert ok, f"range_budget ES failed: {msg}"


def test_range_budget_mgc_passes_gates(mgc_loaded):
    bars = RangeBudgetEngine().run(
        mgc_loaded, symbol="MGC",
        range_k=1.5,
    )
    bdf = bars_to_dataframe(bars)
    assert len(bdf) > 500
    ok, msg = _evaluate_engine(mgc_loaded, bdf, family="gold")
    assert ok, f"range_budget MGC failed: {msg}"


# ============================================================================
# Family classifier sanity
# ============================================================================

def test_family_classifier_sanity():
    from sfpe.data.families import asset_class_of, band_for_family
    assert asset_class_of("sp500") == "equity"
    assert asset_class_of("gold") == "commodity"
    assert band_for_family("sp500") == (12, 25)
    assert band_for_family("oil") == (10, 20)
    with pytest.raises(ValueError):
        asset_class_of("UNKNOWN_FAMILY")


def test_autocorr_gate_logic():
    # source far from zero -> relative test
    ok, _ = autocorr_gate(0.10, 0.10)
    assert ok
    ok, _ = autocorr_gate(0.15, 0.10)
    assert not ok                      # 50% deviation, fails 20%
    # source near zero -> absolute test
    ok, _ = autocorr_gate(0.02, 0.001)
    assert ok                          # |synth| < 0.05
    ok, _ = autocorr_gate(0.10, 0.001)
    assert not ok                      # |synth| > 0.05
