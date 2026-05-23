"""Pydantic schemas for SFPE-5M data structures.

Kept deliberately small in v1. Expanded as later phases land.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class InstrumentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    file: str
    tick_size: float
    point_value: float
    tick_value: float
    calendar: str
    dataset_start: date
    family: str
    latest_entry_time: str


class CalendarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_et: str
    end_et: str
    timezone: str = "America/New_York"
    expected_bars: int
    short_session_threshold_pct: float = 0.50


class IntegrityReportRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    n_bars: int
    n_sessions: int
    expected_bars_per_session: int
    median_bars_per_session: int
    missing_gaps: int
    duplicates: int
    ohlc_violations: int
    bad_volume: int
    zero_volume_bars: int
    outlier_bars: int
    short_sessions: int
    half_day_sessions: int
    out_of_rth_bars: int
    dataset_start: str
    dataset_end: str
    verdict: str            # "PASS" or "WARN" or "FAIL"
    notes: Optional[str] = None
