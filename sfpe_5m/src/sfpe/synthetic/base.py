"""Shared synthetic-engine base types.

All engines emit a list of `SyntheticBar` objects. Every bar is constrained to
a single RTH session (never spans). Engines must be strictly causal: at source
bar t, only data through t may influence the synthetic state.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import List, Optional

import pandas as pd


@dataclass
class SyntheticBar:
    engine: str
    symbol: str
    session_date: object
    start_idx: int           # source-bar index of synthetic open (inclusive)
    end_idx: int             # source-bar index of synthetic close (inclusive)
    open_time: pd.Timestamp
    close_time: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    n_source_bars: int
    notional: float = 0.0
    signed_notional: float = 0.0
    variance: float = 0.0
    log_return: float = float("nan")
    reason: str = ""        # one of: budget, max_bars, session_end

    def to_dict(self) -> dict:
        d = asdict(self)
        # serialize timestamps as ISO strings WITH timezone info preserved (when available)
        d["open_time"] = (
            pd.Timestamp(self.open_time).isoformat() if self.open_time is not None else None
        )
        d["close_time"] = (
            pd.Timestamp(self.close_time).isoformat() if self.close_time is not None else None
        )
        d["session_date"] = str(self.session_date)
        return d


def bars_to_dataframe(bars: List[SyntheticBar]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=[
            "engine", "symbol", "session_date", "start_idx", "end_idx",
            "open_time", "close_time", "open", "high", "low", "close",
            "volume", "n_source_bars", "notional", "signed_notional",
            "variance", "log_return", "reason",
        ])
    return pd.DataFrame([b.to_dict() for b in bars])


class BaseEngine(ABC):
    """Abstract base for all synthetic-candle engines."""

    name: str = "base"

    @abstractmethod
    def run(self, df: pd.DataFrame, symbol: str, **kwargs) -> List[SyntheticBar]:
        """Run engine on a loaded, derived DataFrame.

        Concrete implementations MUST:
          - never read df.iloc[j] for any j > the current source bar index.
          - close any in-progress synthetic at the last bar of each session.
          - emit SyntheticBar.reason in {"budget", "max_bars", "session_end"}.
        """


def parkinson_variance(high: float, low: float) -> float:
    """Parkinson variance estimator for a single bar: ln(H/L)^2 / (4 ln 2)."""
    if high <= 0 or low <= 0 or high < low or high == low:
        return 0.0
    return (math.log(high / low) ** 2) / (4.0 * math.log(2.0))
