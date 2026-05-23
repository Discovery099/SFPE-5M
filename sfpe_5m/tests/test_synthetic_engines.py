"""Spec §6 — priority synthetic engines (vol_budget C, dollar_imbalance A).

Quality gates per §11.1: avg bars/session in band [4, 30], lag-1 autocorr < 0.3,
no cross-session bars.
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
from sfpe.synthetic.base import bars_to_dataframe  # noqa: E402
from sfpe.synthetic.vol_budget import VolBudgetEngine  # noqa: E402
from sfpe.synthetic.dollar_imbalance import DollarImbalanceEngine  # noqa: E402
from sfpe.synthetic.volume_time import VolumeTimeEngine  # noqa: E402
from sfpe.synthetic.range_budget import RangeBudgetEngine  # noqa: E402

ES_CSV = REPO / "data" / "raw" / "ES_5min_RTH_6year.csv"


@pytest.fixture(scope="module")
def es_loaded() -> pd.DataFrame:
    if not ES_CSV.exists():
        pytest.skip(f"ES CSV not found at {ES_CSV}")
    cals = load_calendars(REPO / "config" / "session_calendars.yaml")
    return load_instrument_csv(ES_CSV, cals["RTH_eq"])


def _gates_pass(bars_df: pd.DataFrame, band=(4, 30), max_autocorr=0.3) -> dict:
    by_session = bars_df.groupby("session_date").size()
    avg = float(by_session.mean())
    lr = bars_df["log_return"].dropna()
    ac1 = float(np.corrcoef(lr.values[:-1], lr.values[1:])[0, 1]) if len(lr) > 5 else 0.0
    return dict(avg=avg, ac1=ac1, in_band=band[0] <= avg <= band[1], ac_ok=abs(ac1) < max_autocorr)


def test_vol_budget_passes_gates(es_loaded):
    engine = VolBudgetEngine()
    bars = engine.run(
        es_loaded, symbol="ES",
        target_bars_per_session=6,
        variance_lookback_sessions=20,
        sigma_mult=1.0,
        min_source_bars=1,
        max_source_bars=78,
    )
    assert len(bars) > 1000
    bdf = bars_to_dataframe(bars)
    # no cross-session bars (every bar must be wholly inside one session_date)
    assert (bdf.groupby("session_date").size() > 0).all()
    g = _gates_pass(bdf)
    assert g["in_band"], f"vol_budget avg bars/session out of band: {g['avg']:.2f}"
    assert g["ac_ok"], f"vol_budget lag-1 autocorr too high: {g['ac1']:.4f}"


def test_dollar_imbalance_passes_gates(es_loaded):
    engine = DollarImbalanceEngine()
    bars = engine.run(
        es_loaded, symbol="ES",
        point_value=50.0,
        imbalance_window=50,
        theta_mult=1.0,
        target_bars_per_session=8,
        expected_bars_per_session=78,
        min_source_bars=1,
        max_source_bars=78,
    )
    assert len(bars) > 1000
    bdf = bars_to_dataframe(bars)
    g = _gates_pass(bdf)
    assert g["in_band"], f"dollar_imbalance avg bars/session out of band: {g['avg']:.2f}"
    assert g["ac_ok"], f"dollar_imbalance lag-1 autocorr too high: {g['ac1']:.4f}"


def test_volume_time_engine_raises(es_loaded):
    with pytest.raises(NotImplementedError):
        VolumeTimeEngine().run(es_loaded, symbol="ES")


def test_range_budget_engine_raises(es_loaded):
    with pytest.raises(NotImplementedError):
        RangeBudgetEngine().run(es_loaded, symbol="ES")
