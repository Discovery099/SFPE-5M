"""Session-calendar handling for SFPE-5M.

Loads YAML calendar definitions, provides RTH membership tests, computes the
session_date for each timestamp, and supports filtering source bars to RTH.

All times are interpreted in America/New_York. The session_date is the ET date
on which the bar's timestamp falls during the session start..end window.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Dict

import pandas as pd
import yaml


@dataclass(frozen=True)
class Calendar:
    name: str
    start_et: time
    end_et: time
    timezone: str
    expected_bars: int
    short_session_threshold_pct: float

    @property
    def start_str(self) -> str:
        return f"{self.start_et.hour:02d}:{self.start_et.minute:02d}"

    @property
    def end_str(self) -> str:
        return f"{self.end_et.hour:02d}:{self.end_et.minute:02d}"


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def load_calendars(yaml_path: Path) -> Dict[str, Calendar]:
    raw = yaml.safe_load(Path(yaml_path).read_text())
    cals: Dict[str, Calendar] = {}
    for name, cfg in raw["calendars"].items():
        cals[name] = Calendar(
            name=name,
            start_et=_parse_hhmm(cfg["start_et"]),
            end_et=_parse_hhmm(cfg["end_et"]),
            timezone=cfg.get("timezone", "America/New_York"),
            expected_bars=int(cfg["expected_bars"]),
            short_session_threshold_pct=float(cfg.get("short_session_threshold_pct", 0.50)),
        )
    return cals


def is_in_rth(timestamp_et: pd.Timestamp, cal: Calendar) -> bool:
    """True iff the bar's timestamp (already in ET) is within [start_et, end_et).

    Bars are start-of-bar convention: a 5-min bar timestamped 09:30 covers
    09:30..09:35 inclusive of 09:30, exclusive of 09:35. Thus the last in-RTH bar
    for a 09:30..16:00 calendar is 15:55.
    """
    t = timestamp_et.time()
    return (t >= cal.start_et) and (t < cal.end_et)


def tag_rth(df: pd.DataFrame, cal: Calendar, ts_col: str = "timestamp") -> pd.DataFrame:
    """Add an `out_of_rth` boolean column for each row.

    The input frame must have a timezone-aware `timestamp` column in `cal.timezone`.
    """
    out = df.copy()
    times = df[ts_col].dt.time
    in_rth = (times >= cal.start_et) & (times < cal.end_et)
    out["out_of_rth"] = ~in_rth.values
    return out
