"""Tests for src/sfpe/data/roll_detection.py.

Phase 5 Step 1 (v1.4):
- The v1.4 detector must produce fewer flags than the legacy 5×ATR-only mode.
- The detector must be causal (no lookahead): truncating tail sessions must not
  change flags emitted on retained sessions.
- The calendar gate must block flags whose date_next falls in a non-roll month.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sfpe.data.roll_detection import (
    detect_rolls,
    RollDetectionParams,
)


def _make_synth_df(
    sessions: list[pd.Timestamp],
    *,
    base_open: float = 100.0,
    atr: float = 1.0,
    gap_after_sessions: dict[pd.Timestamp, float] | None = None,
    vol_zscore_pump_dates: set[pd.Timestamp] | None = None,
    seed: int = 0,
) -> pd.DataFrame:
    """Construct a minimal RTH-bar DataFrame with one bar per session.

    `gap_after_sessions`: maps session_date -> dollar gap to inject as the next
    session's open relative to the prior session's close.
    `vol_zscore_pump_dates`: sessions where we inject anomalously high volume so
    that the candidate session's volume z-score >= 0.5 vs prior 20 sessions.

    Volume has small natural noise (~5%) so that the rolling std is nonzero and
    the z-score is well-defined.
    """
    gap_after_sessions = gap_after_sessions or {}
    vol_zscore_pump_dates = vol_zscore_pump_dates or set()
    rng = np.random.default_rng(seed)

    rows = []
    last_close = base_open
    for sd in sessions:
        # Inject gap if this session_date is in the "next open" target list.
        if sd in gap_after_sessions:
            this_open = last_close + gap_after_sessions[sd]
        else:
            this_open = last_close
        h = this_open + 0.5
        lo = this_open - 0.5
        c = this_open  # flat session, single bar
        # Small natural variance ~5% so rolling std > 0.
        vol_base = float(1000.0 + rng.normal(0, 50))
        vol = vol_base * 5.0 if sd in vol_zscore_pump_dates else vol_base
        rows.append(dict(
            timestamp=pd.Timestamp(sd, tz="America/New_York"),
            symbol="TEST",
            open=this_open,
            high=h,
            low=lo,
            close=c,
            volume=vol,
            session_date=sd.date() if hasattr(sd, "date") else sd,
            atr_20=atr,
        ))
        last_close = c
    return pd.DataFrame(rows)


def _business_days(start: str, n: int) -> list[pd.Timestamp]:
    return list(pd.bdate_range(start=start, periods=n))


def test_legacy_count_vs_v1_4_count_synthetic():
    """v1.4 must flag <= legacy count (the extra filters can only subtract)."""
    sessions = _business_days("2024-01-02", 100)
    # Inject 10 huge gaps at random sessions across a mix of months.
    rng = np.random.default_rng(42)
    gap_targets = rng.choice(sessions[5:], size=15, replace=False)
    gaps = {pd.Timestamp(s): 50.0 for s in gap_targets}
    df = _make_synth_df(sessions, atr=1.0, gap_after_sessions=gaps,
                        vol_zscore_pump_dates=set(map(pd.Timestamp, gap_targets)))
    legacy = detect_rolls(df, family="sp500", legacy_mode=True)
    v14 = detect_rolls(df, family="sp500", legacy_mode=False)
    assert len(legacy) >= len(v14), (
        f"v1.4 must flag <= legacy; got legacy={len(legacy)} v1.4={len(v14)}"
    )
    # And legacy should catch at least most of the big gaps (>5x ATR).
    assert len(legacy) >= 10


def test_calendar_gate_blocks_non_roll_month_gap():
    """A huge gap in a non-roll month must NOT be flagged in v1.4 (sp500 family).

    Sp500 roll months = {3, 6, 9, 12}. We inject the gap in May (non-roll).
    """
    sessions = _business_days("2024-04-01", 60)  # mostly April–May
    # Pick a date in May 2024.
    may_dates = [s for s in sessions if s.month == 5]
    assert len(may_dates) > 0, "test sessions should include May"
    gap_date = may_dates[10]
    df = _make_synth_df(
        sessions, atr=1.0,
        gap_after_sessions={gap_date: 100.0},
        vol_zscore_pump_dates={gap_date},
    )
    v14 = detect_rolls(df, family="sp500", legacy_mode=False)
    # Calendar gate must block this May gap.
    flagged_dates = pd.to_datetime(v14["date_next"]).dt.month.tolist()
    assert 5 not in flagged_dates, (
        f"v1.4 should not flag a May gap for sp500 (roll-months 3/6/9/12); "
        f"got months: {flagged_dates}"
    )


def test_calendar_gate_allows_roll_month_gap():
    """A huge gap in a roll month MUST be flagged in v1.4."""
    # Start ~3 months early so the vol-zscore 20-session warmup is satisfied
    # before we hit March.
    sessions = _business_days("2024-01-02", 120)
    march_dates = [s for s in sessions if s.month == 3]
    assert len(march_dates) > 5
    gap_date = march_dates[5]
    df = _make_synth_df(
        sessions, atr=1.0,
        gap_after_sessions={gap_date: 100.0},
        vol_zscore_pump_dates={gap_date},
    )
    v14 = detect_rolls(df, family="sp500", legacy_mode=False)
    flagged_dates = pd.to_datetime(v14["date_next"]).dt.date.tolist()
    assert any(d == gap_date.date() for d in flagged_dates), (
        f"v1.4 must flag a roll-month gap; got: {flagged_dates}"
    )


def test_no_lookahead_drop_last_K_sessions():
    """Truncating the last K sessions must not change earlier-session flags."""
    sessions = _business_days("2024-01-02", 120)
    rng = np.random.default_rng(7)
    gap_targets = rng.choice(sessions[20:80], size=8, replace=False)
    gaps = {pd.Timestamp(s): 30.0 for s in gap_targets}
    df = _make_synth_df(
        sessions, atr=1.0, gap_after_sessions=gaps,
        vol_zscore_pump_dates=set(map(pd.Timestamp, gap_targets)),
    )
    full = detect_rolls(df, family="sp500", legacy_mode=False)
    full_sorted = full.sort_values("date_next").reset_index(drop=True)
    # Truncate last 20 sessions.
    keep_sessions = sessions[:-20]
    df_trunc = df[df["session_date"].isin([s.date() for s in keep_sessions])]
    trunc = detect_rolls(df_trunc, family="sp500", legacy_mode=False)
    # All flags in trunc must appear in full (i.e. earlier flags unchanged).
    full_set = set(pd.to_datetime(full_sorted["date_next"]).astype(str).tolist())
    trunc_set = set(pd.to_datetime(trunc["date_next"]).astype(str).tolist())
    assert trunc_set.issubset(full_set), (
        f"truncated detector produced flags not in full run: {trunc_set - full_set}"
    )


def test_v1_4_default_threshold_is_8x_atr():
    """User-locked default per Phase 5 Step 1."""
    p = RollDetectionParams()
    assert p.atr_mult == 8.0
    assert p.days_window == 8
    assert p.vol_zscore_min == 0.5
    assert p.require_all_conditions is True


def test_v1_4_requires_all_three_conditions_by_default():
    """A row with gap+cal but no vol-z must be filtered out under default v1.4."""
    sessions = _business_days("2024-02-26", 80)
    march_dates = [s for s in sessions if s.month == 3]
    gap_date = march_dates[5]
    # NO volume pump → vol z-score will be ~0
    df = _make_synth_df(
        sessions, atr=1.0,
        gap_after_sessions={gap_date: 100.0},
        vol_zscore_pump_dates=set(),
    )
    v14 = detect_rolls(df, family="sp500", legacy_mode=False)
    flagged_dates = pd.to_datetime(v14["date_next"]).dt.date.tolist()
    assert gap_date.date() not in flagged_dates, (
        "v1.4 must NOT flag rows without volume signature"
    )


def test_oil_family_uses_monthly_calendar():
    """Oil (MCL) roll months = all 12 — calendar gate should never block."""
    sessions = _business_days("2024-04-01", 60)
    may_dates = [s for s in sessions if s.month == 5]
    gap_date = may_dates[10]
    df = _make_synth_df(
        sessions, atr=1.0,
        gap_after_sessions={gap_date: 100.0},
        vol_zscore_pump_dates={gap_date},
    )
    v14 = detect_rolls(df, family="oil", legacy_mode=False)
    flagged_dates = pd.to_datetime(v14["date_next"]).dt.date.tolist()
    assert gap_date.date() in flagged_dates, (
        "oil family flags should not be blocked by month (monthly contract)"
    )
