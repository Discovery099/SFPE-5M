"""Mandatory no-lookahead tests (spec §11.4-style) for every Phase-3 feature.

For each feature we run on full data and on truncated data df.iloc[:cut], then
assert that every row of the truncated output, indexed before `cut`, is
byte-identical to the same row of the full output. Future-dependent columns
(documented in the feature module) are explicitly excluded.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
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


def _compare_rows(
    full: pd.DataFrame, trunc: pd.DataFrame,
    *, cut: int, exclude_cols: Iterable[str] = (),
) -> tuple[int, str]:
    """Compare full.iloc[:cut] vs trunc.iloc[:cut] except excluded columns.

    Truncated runs may legitimately produce DIFFERENT values for rows close to
    the truncation boundary when a feature uses a window that crosses cut
    (e.g., a rolling future-horizon classifier). To respect that, callers use
    `exclude_cols` and we also drop the last `confirmation_bars` rows when
    needed -- but for STRICT causal features no such margin is needed.
    """
    cols = [c for c in full.columns if c not in exclude_cols]
    f = full.iloc[:cut][cols].reset_index(drop=True)
    t = trunc.iloc[:cut][cols].reset_index(drop=True)
    mismatches = 0
    first_fail = ""
    for i in range(cut):
        for c in cols:
            fv = f.iloc[i][c]
            tv = t.iloc[i][c]
            if pd.isna(fv) and pd.isna(tv):
                continue
            if isinstance(fv, float) and isinstance(tv, float):
                if not math.isclose(fv, tv, rel_tol=1e-9, abs_tol=1e-9):
                    mismatches += 1
                    if not first_fail:
                        first_fail = f"row={i} col={c} full={fv} trunc={tv}"
                    break
            else:
                if fv != tv:
                    mismatches += 1
                    if not first_fail:
                        first_fail = f"row={i} col={c} full={fv} trunc={tv}"
                    break
    return mismatches, first_fail


def test_no_lookahead_absorption(es_loaded):
    df = es_loaded
    cut = int(0.5 * len(df))
    full = compute_absorption(df, family="sp500", tick_size=0.25)
    df_t = df.iloc[:cut].reset_index(drop=True).copy()
    trunc = compute_absorption(df_t, family="sp500", tick_size=0.25)
    mismatches, first_fail = _compare_rows(full, trunc, cut=cut)
    assert mismatches == 0, f"absorption lookahead violation: {first_fail}"


def test_no_lookahead_vacuum(es_loaded):
    df = es_loaded
    cut = int(0.5 * len(df))
    full = compute_vacuum(df, family="sp500")
    df_t = df.iloc[:cut].reset_index(drop=True).copy()
    trunc = compute_vacuum(df_t, family="sp500")
    # realized_classification is POST-HOC by design; vacuum_flag (causal) is
    # the signal column. Exclude post-hoc columns from the strict comparison.
    # Also exclude the last `confirmation_bars` rows since post-hoc may be NaN
    # there vs realized in full.
    POST_HOC = {"realized_classification"}
    margin = 3   # confirmation_bars default
    mismatches, first_fail = _compare_rows(
        full.iloc[:cut - margin], trunc.iloc[:cut - margin],
        cut=cut - margin, exclude_cols=POST_HOC,
    )
    assert mismatches == 0, f"vacuum lookahead violation: {first_fail}"


def test_no_lookahead_regime(es_loaded):
    df = es_loaded
    cut = int(0.5 * len(df))
    full = compute_regime(df)
    df_t = df.iloc[:cut].reset_index(drop=True).copy()
    trunc = compute_regime(df_t)
    mismatches, first_fail = _compare_rows(full, trunc, cut=cut)
    assert mismatches == 0, f"regime lookahead violation: {first_fail}"


def test_no_lookahead_vpin(es_loaded):
    df = es_loaded
    cut = int(0.5 * len(df))
    full = compute_vpin(df, tick_size=0.25)
    df_t = df.iloc[:cut].reset_index(drop=True).copy()
    trunc = compute_vpin(df_t, tick_size=0.25)
    mismatches, first_fail = _compare_rows(full, trunc, cut=cut)
    assert mismatches == 0, f"vpin lookahead violation: {first_fail}"


def test_no_lookahead_tpo(es_loaded):
    df = es_loaded
    cut = int(0.5 * len(df))
    # Choose cut at a session boundary to make session-level outputs equivalent.
    cut_sd = df.iloc[cut]["session_date"]
    cut = df[df["session_date"] == cut_sd].index.min()
    full = compute_tpo(df, tick_size=0.25)
    df_t = df.iloc[:cut].reset_index(drop=True).copy()
    trunc = compute_tpo(df_t, tick_size=0.25)
    mismatches, first_fail = _compare_rows(full, trunc, cut=cut)
    assert mismatches == 0, f"tpo lookahead violation: {first_fail}"


def test_no_lookahead_magnitude_projection(es_loaded):
    df = es_loaded
    # All upstream features computed first.
    a = compute_absorption(df, family="sp500", tick_size=0.25)
    v = compute_vacuum(df, family="sp500")
    r = compute_regime(df)
    vp = compute_vpin(df, tick_size=0.25)
    tpo = compute_tpo(df, tick_size=0.25)
    bars_full = VolBudgetEngine().run(
        df, symbol="ES", target_bars_per_session=18,
        variance_lookback_sessions=20, sigma_mult=1.0,
        variance_proxy="parkinson", min_source_bars=1, max_source_bars=78,
    )
    bdf_full = bars_to_dataframe(bars_full)
    mp_full = compute_magnitude_projection(
        bdf_full, source_df=df, feature_regime=r, feature_vpin=vp,
        feature_absorption=a, feature_vacuum=v, feature_tpo=tpo,
        expected_bars_per_session=78,
    )

    # Truncate to first half. Synthetic bars whose start/end are entirely in
    # the first half MUST produce identical magnitude rows.
    cut = int(0.5 * len(df))
    df_t = df.iloc[:cut].reset_index(drop=True).copy()
    a_t = a.iloc[:cut].reset_index(drop=True).copy()
    v_t = v.iloc[:cut].reset_index(drop=True).copy()
    r_t = r.iloc[:cut].reset_index(drop=True).copy()
    vp_t = vp.iloc[:cut].reset_index(drop=True).copy()
    tpo_t = tpo.iloc[:cut].reset_index(drop=True).copy()
    bars_t = VolBudgetEngine().run(
        df_t, symbol="ES", target_bars_per_session=18,
        variance_lookback_sessions=20, sigma_mult=1.0,
        variance_proxy="parkinson", min_source_bars=1, max_source_bars=78,
    )
    bdf_t = bars_to_dataframe(bars_t)
    mp_t = compute_magnitude_projection(
        bdf_t, source_df=df_t, feature_regime=r_t, feature_vpin=vp_t,
        feature_absorption=a_t, feature_vacuum=v_t, feature_tpo=tpo_t,
        expected_bars_per_session=78,
    )

    # Compare only synth bars whose end_idx < cut - 1 (safely inside both runs)
    common = min(len(mp_full), len(mp_t))
    safe_mask = bdf_full["end_idx"].iloc[:common].values < (cut - 1)
    # Compare row-by-row
    cols = ["expected_abs_return_q20", "expected_abs_return_q50", "expected_abs_return_q80",
            "expected_range_q20", "expected_range_q50", "expected_range_q80",
            "expected_duration_q20", "expected_duration_q50", "expected_duration_q80",
            "state_confidence", "pooling_level", "stress_flag"]
    f = mp_full.iloc[:common][cols].reset_index(drop=True)
    t = mp_t.iloc[:common][cols].reset_index(drop=True)
    mismatches = 0
    first_fail = ""
    for i in range(common):
        if not safe_mask[i]:
            continue
        for c in cols:
            fv, tv = f.iloc[i][c], t.iloc[i][c]
            if pd.isna(fv) and pd.isna(tv):
                continue
            if isinstance(fv, float) and isinstance(tv, float):
                if not math.isclose(fv, tv, rel_tol=1e-9, abs_tol=1e-9):
                    mismatches += 1
                    if not first_fail:
                        first_fail = f"row={i} col={c} full={fv} trunc={tv}"
                    break
            else:
                if fv != tv:
                    mismatches += 1
                    if not first_fail:
                        first_fail = f"row={i} col={c} full={fv} trunc={tv}"
                    break
    assert mismatches == 0, f"magnitude_projection lookahead violation: {first_fail}"
