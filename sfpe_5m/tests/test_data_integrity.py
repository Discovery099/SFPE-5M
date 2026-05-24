"""Spec §§5.1–5.2 — data loader + integrity tests on the real ES CSV."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.data.calendar import load_calendars  # noqa: E402
from sfpe.data.loader import load_instrument_csv, DERIVED_COLUMNS  # noqa: E402
from sfpe.data.integrity import compute_integrity  # noqa: E402
from sfpe.data.roll_detection import detect_rolls  # noqa: E402

ES_CSV = REPO / "data" / "raw" / "ES_5min_RTH_6year.csv"


@pytest.fixture(scope="module")
def es_loaded() -> pd.DataFrame:
    if not ES_CSV.exists():
        pytest.skip(f"ES CSV not found at {ES_CSV}")
    cals = load_calendars(REPO / "config" / "session_calendars.yaml")
    return load_instrument_csv(ES_CSV, cals["RTH_eq"])


def test_loader_derives_all_columns(es_loaded):
    df = es_loaded
    for col in DERIVED_COLUMNS:
        assert col in df.columns, f"missing derived column {col}"


def test_timezone_is_NY(es_loaded):
    assert str(es_loaded["timestamp"].dt.tz) == "America/New_York"


def test_first_bar_log_return_is_nan(es_loaded):
    df = es_loaded
    n_nan = int(df.loc[df["is_first_bar_of_session"], "log_return"].notna().sum())
    assert n_nan == 0, "log_return at session start must be NaN (chain breaks)"


def test_atr_20_no_negative(es_loaded):
    df = es_loaded
    assert (df["atr_20"].dropna() >= 0).all()


def test_no_ohlc_violations(es_loaded):
    df = es_loaded
    bad = (
        (df["high"] < df[["open", "close"]].max(axis=1))
        | (df["low"] > df[["open", "close"]].min(axis=1))
        | (df["high"] < df["low"])
    ).sum()
    assert bad == 0


def test_integrity_verdict_not_fail(es_loaded):
    rep = compute_integrity(
        es_loaded,
        symbol="ES",
        expected_bars=78,
        short_session_threshold_pct=0.50,
    )
    assert rep["verdict"] in ("PASS", "WARN"), f"unexpected ES verdict {rep['verdict']}"
    assert rep["duplicates"] == 0
    assert rep["ohlc_violations"] == 0
    assert rep["bad_volume"] == 0


def test_roll_candidates_are_dataframe(es_loaded):
    rolls = detect_rolls(es_loaded, family="sp500")
    assert isinstance(rolls, pd.DataFrame)
    # v1.4 detector: ES typically 16-30 candidates over ~5 years
    assert 5 <= len(rolls) <= 100
    if not rolls.empty:
        for col in ["symbol", "date_prev", "date_next", "close_prev", "open_next",
                    "gap", "gap_atr_mult", "conditions_met"]:
            assert col in rolls.columns
