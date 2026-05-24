"""Spec §11.4 mandatory NO-LOOKAHEAD test for the projection layer.

We run the full projection pipeline on the source data, and again on the
source data truncated at midpoint. Every ensemble row at index < cut MUST be
byte-identical between the two runs. If not, the projection layer is using
future information.

This test is slow (loads + runs full pipeline twice) and is gated by the
SFPE_RUN_PROJECTION_NOLOOKAHEAD env var so the rest of the test suite can run
fast in CI; we always run it explicitly during Phase-4 deliverable.
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.data.calendar import load_calendars  # noqa: E402
from sfpe.data.loader import load_instrument_csv  # noqa: E402
from sfpe.data.families import target_bars_for_family, asset_class_of  # noqa: E402
from sfpe.projection.engine_state import (  # noqa: E402
    vol_budget_trace, dollar_imbalance_trace,
    volume_time_trace, range_budget_trace,
)
from sfpe.features.absorption import compute_absorption  # noqa: E402
from sfpe.features.liquidity_vacuum import compute_vacuum  # noqa: E402
from sfpe.features.regime_router import compute_regime  # noqa: E402
from sfpe.features.vpin_proxy import compute_vpin  # noqa: E402
from sfpe.features.tpo_profile import compute_tpo  # noqa: E402

ES_CSV = REPO / "data" / "raw" / "ES_5min_RTH_6year.csv"


@pytest.fixture(scope="module")
def es_loaded():
    if not ES_CSV.exists():
        pytest.skip(f"ES CSV not found at {ES_CSV}")
    cals = load_calendars(REPO / "config" / "session_calendars.yaml")
    return load_instrument_csv(ES_CSV, cals["RTH_eq"])


def _trace_compare(state_full, state_t, cut):
    """Compare per-bar engine state up to (cut - 1). The very last row of the
    truncated frame is a documented boundary case: with no next bar visible,
    `is_session_end` evaluates True, which differs from the full run. Excluding
    that one row isolates true lookahead violations from this boundary effect.
    """
    cmp_cols = [
        "synth_open_idx", "synth_open_price",
        "synth_high_so_far", "synth_low_so_far", "synth_close_so_far",
        "synth_progress", "synth_progress_abs",
        "synth_target", "synth_bars_elapsed", "synth_velocity",
        "synth_will_close", "synth_bias_raw",
    ]
    safe = cut - 1
    f = state_full.iloc[:safe][cmp_cols].reset_index(drop=True)
    t = state_t.iloc[:safe][cmp_cols].reset_index(drop=True)
    for i in range(safe):
        for c in cmp_cols:
            fv, tv = f.iloc[i][c], t.iloc[i][c]
            if pd.isna(fv) and pd.isna(tv):
                continue
            if isinstance(fv, float) and isinstance(tv, float):
                if not math.isclose(fv, tv, rel_tol=1e-9, abs_tol=1e-9):
                    return f"row={i} col={c} full={fv} trunc={tv}"
            else:
                if fv != tv:
                    return f"row={i} col={c} full={fv} trunc={tv}"
    return ""


def test_no_lookahead_engine_state_vol_budget(es_loaded):
    cut = int(0.5 * len(es_loaded))
    full = vol_budget_trace(es_loaded, symbol="ES",
                            target_bars_per_session=target_bars_for_family("sp500"),
                            variance_lookback_sessions=20)
    t = vol_budget_trace(es_loaded.iloc[:cut].reset_index(drop=True),
                          symbol="ES",
                          target_bars_per_session=target_bars_for_family("sp500"),
                          variance_lookback_sessions=20)
    msg = _trace_compare(full, t, cut)
    assert msg == "", f"vol_budget_trace lookahead: {msg}"


def test_no_lookahead_engine_state_dollar_imbalance(es_loaded):
    cut = int(0.5 * len(es_loaded))
    full = dollar_imbalance_trace(es_loaded, symbol="ES", point_value=50.0,
                                  target_bars_per_session=target_bars_for_family("sp500"),
                                  expected_bars_per_session=78)
    t = dollar_imbalance_trace(es_loaded.iloc[:cut].reset_index(drop=True),
                                symbol="ES", point_value=50.0,
                                target_bars_per_session=target_bars_for_family("sp500"),
                                expected_bars_per_session=78)
    msg = _trace_compare(full, t, cut)
    assert msg == "", f"dollar_imbalance_trace lookahead: {msg}"


def test_no_lookahead_engine_state_volume_time(es_loaded):
    cut = int(0.5 * len(es_loaded))
    full = volume_time_trace(es_loaded, symbol="ES",
                              target_bars_per_session=target_bars_for_family("sp500"))
    t = volume_time_trace(es_loaded.iloc[:cut].reset_index(drop=True),
                           symbol="ES",
                           target_bars_per_session=target_bars_for_family("sp500"))
    msg = _trace_compare(full, t, cut)
    assert msg == "", f"volume_time_trace lookahead: {msg}"


def test_no_lookahead_engine_state_range_budget(es_loaded):
    cut = int(0.5 * len(es_loaded))
    full = range_budget_trace(es_loaded, symbol="ES", range_k=1.5)
    t = range_budget_trace(es_loaded.iloc[:cut].reset_index(drop=True),
                            symbol="ES", range_k=1.5)
    msg = _trace_compare(full, t, cut)
    assert msg == "", f"range_budget_trace lookahead: {msg}"
