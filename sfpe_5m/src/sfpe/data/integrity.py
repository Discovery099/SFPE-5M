"""Spec §5.2 integrity checks.

Produces a per-instrument integrity report with PASS / WARN / FAIL verdict.
Nothing is removed silently — anomalies are counted and reported.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd


def compute_integrity(
    df: pd.DataFrame,
    *,
    symbol: str,
    expected_bars: int,
    short_session_threshold_pct: float,
) -> Dict[str, object]:
    """Compute spec-§5.2 integrity metrics for one instrument's loaded frame.

    The frame must already have all spec-§5.1 derived columns (use loader.py).
    Returns a plain dict suitable for writing to CSV / markdown.
    """
    n_bars = len(df)

    # Missing timestamps: gap > 5 minutes between consecutive same-session bars.
    delta_min = df["timestamp"].diff().dt.total_seconds() / 60.0
    same_sess = df["session_date"] == df["session_date"].shift(1)
    missing_gaps = int(((delta_min > 5.0) & same_sess).sum())

    # Duplicates (same timestamp + symbol).
    duplicates = int(df.duplicated(subset=["timestamp", "symbol"]).sum())

    # OHLC violations.
    ohlc_violations = int((
        (df["high"] < df[["open", "close"]].max(axis=1))
        | (df["low"] > df[["open", "close"]].min(axis=1))
        | (df["high"] < df["low"])
    ).sum())

    # Negative / null volume.
    bad_volume = int(((df["volume"] < 0) | df["volume"].isna()).sum())

    # Zero-volume RTH bars (counted, not removed).
    zero_volume_bars = int((df["volume"] == 0).sum())

    # Outlier bars: |price_return| > 10 * ATR_20.
    pr = df["price_return"].abs()
    atr = df["atr_20"]
    outlier_bars = int(((pr > 10.0 * atr) & atr.notna() & pr.notna()).sum())

    # Per-session bar counts.
    sessions = df.groupby("session_date").size()
    n_sessions = int(sessions.size)
    short_thresh = int(expected_bars * short_session_threshold_pct)
    half_thresh = int(expected_bars * 0.40)
    short_sessions = int((sessions < short_thresh).sum())
    half_day_sessions = int(((sessions >= half_thresh) & (sessions < short_thresh)).sum())
    median_bars_per_session = int(sessions.median())

    out_of_rth_bars = int(df.attrs.get("out_of_rth_bars", 0))

    # Verdict logic. PASS unless any of the following hard failures:
    #   - duplicates > 0
    #   - ohlc_violations > 0
    #   - bad_volume > 0
    # WARN if any soft issue (missing gaps, outliers > 0, short sessions > 5).
    if duplicates > 0 or ohlc_violations > 0 or bad_volume > 0:
        verdict = "FAIL"
    elif missing_gaps > 0 or outlier_bars > 0 or short_sessions > 5:
        verdict = "WARN"
    else:
        verdict = "PASS"

    notes = []
    if out_of_rth_bars:
        notes.append(f"out_of_rth_bars={out_of_rth_bars} (excluded from synthetic engines)")
    if zero_volume_bars:
        notes.append(f"zero_volume_bars={zero_volume_bars} (kept, tagged)")
    if outlier_bars:
        notes.append(f"outlier_bars={outlier_bars} (|ret| > 10*ATR)")
    if missing_gaps:
        notes.append(f"missing_gaps={missing_gaps} within-session")
    if short_sessions:
        notes.append(f"short_sessions={short_sessions}")
    notes_str = " ; ".join(notes) if notes else None

    return dict(
        symbol=symbol,
        n_bars=n_bars,
        n_sessions=n_sessions,
        expected_bars_per_session=expected_bars,
        median_bars_per_session=median_bars_per_session,
        missing_gaps=missing_gaps,
        duplicates=duplicates,
        ohlc_violations=ohlc_violations,
        bad_volume=bad_volume,
        zero_volume_bars=zero_volume_bars,
        outlier_bars=outlier_bars,
        short_sessions=short_sessions,
        half_day_sessions=half_day_sessions,
        out_of_rth_bars=out_of_rth_bars,
        dataset_start=str(df["session_date"].min()),
        dataset_end=str(df["session_date"].max()),
        verdict=verdict,
        notes=notes_str,
    )


def session_bars_count(df: pd.DataFrame) -> pd.Series:
    """Return bars-per-session series (used for the heatmap)."""
    return df.groupby("session_date").size().rename("bars")
