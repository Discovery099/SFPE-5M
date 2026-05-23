"""Mandatory spec §11.4 NO-LOOKAHEAD test.

For each engine, run on full data and on truncated-at-midpoint data. Every
synthetic bar produced by the truncated run whose end_idx is strictly less than
trunc-1 MUST be byte-identical to its counterpart in the full run.

If any engine fails this test, the build is invalid — the engine has used
future information.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Callable

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.data.calendar import load_calendars  # noqa: E402
from sfpe.data.loader import load_instrument_csv  # noqa: E402
from sfpe.synthetic.base import bars_to_dataframe  # noqa: E402
from sfpe.synthetic.vol_budget import VolBudgetEngine  # noqa: E402
from sfpe.synthetic.dollar_imbalance import DollarImbalanceEngine  # noqa: E402

ES_CSV = REPO / "data" / "raw" / "ES_5min_RTH_6year.csv"


@pytest.fixture(scope="module")
def es_loaded() -> pd.DataFrame:
    if not ES_CSV.exists():
        pytest.skip(f"ES CSV not found at {ES_CSV}")
    cals = load_calendars(REPO / "config" / "session_calendars.yaml")
    return load_instrument_csv(ES_CSV, cals["RTH_eq"])


def _compare_no_lookahead(df: pd.DataFrame, run_fn: Callable, trunc_frac: float = 0.5) -> tuple[int, int, str]:
    full = bars_to_dataframe(run_fn(df))
    cut = int(len(df) * trunc_frac)
    df_trunc = df.iloc[:cut].reset_index(drop=True).copy()
    trunc = bars_to_dataframe(run_fn(df_trunc))
    # only compare bars that ended strictly BEFORE the truncation boundary
    trunc_safe = trunc[trunc["end_idx"] < cut - 1].copy()
    full_indexed = full.set_index("start_idx")
    mismatches = 0
    first_fail = ""
    cols = ["end_idx", "open", "high", "low", "close", "volume",
            "n_source_bars", "signed_notional", "variance", "log_return", "reason"]
    for _, t_row in trunc_safe.iterrows():
        sidx = t_row["start_idx"]
        if sidx not in full_indexed.index:
            mismatches += 1
            if not first_fail:
                first_fail = f"start_idx={sidx} missing in full run"
            continue
        f_row = full_indexed.loc[sidx]
        for col in cols:
            tv, fv = t_row[col], f_row[col]
            if isinstance(tv, float) and isinstance(fv, float):
                if math.isnan(tv) and math.isnan(fv):
                    continue
                if not math.isclose(tv, fv, rel_tol=1e-9, abs_tol=1e-9):
                    mismatches += 1
                    if not first_fail:
                        first_fail = f"start_idx={sidx} col={col} trunc={tv} full={fv}"
                    break
            else:
                if tv != fv:
                    mismatches += 1
                    if not first_fail:
                        first_fail = f"start_idx={sidx} col={col} trunc={tv} full={fv}"
                    break
    return mismatches, len(trunc_safe), first_fail


def test_no_lookahead_vol_budget(es_loaded):
    engine = VolBudgetEngine()

    def runner(df_in: pd.DataFrame):
        return engine.run(
            df_in, symbol="ES",
            target_bars_per_session=6,
            variance_lookback_sessions=20,
            sigma_mult=1.0,
            min_source_bars=1,
            max_source_bars=78,
        )

    mismatches, compared, first_fail = _compare_no_lookahead(es_loaded, runner)
    assert mismatches == 0, f"vol_budget no-lookahead violation: {first_fail} (compared={compared})"
    # ensure we actually compared a non-trivial number of bars
    assert compared > 500, f"too few bars compared in no-lookahead test ({compared})"


def test_no_lookahead_dollar_imbalance(es_loaded):
    engine = DollarImbalanceEngine()

    def runner(df_in: pd.DataFrame):
        return engine.run(
            df_in, symbol="ES",
            point_value=50.0,
            imbalance_window=50,
            theta_mult=1.0,
            target_bars_per_session=8,
            expected_bars_per_session=78,
            min_source_bars=1,
            max_source_bars=78,
        )

    mismatches, compared, first_fail = _compare_no_lookahead(es_loaded, runner)
    assert mismatches == 0, f"dollar_imbalance no-lookahead violation: {first_fail} (compared={compared})"
    assert compared > 500, f"too few bars compared in no-lookahead test ({compared})"
