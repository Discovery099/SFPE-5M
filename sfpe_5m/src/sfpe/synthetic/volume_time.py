"""Spec §6 Idea 2 — Volume-Time Synthetic Candles (Engine B).

STUB. Will be implemented in v2.
"""
from __future__ import annotations

from typing import List

import pandas as pd

from .base import BaseEngine, SyntheticBar


class VolumeTimeEngine(BaseEngine):
    name = "volume_time"

    def run(self, df: pd.DataFrame, symbol: str, **kwargs) -> List[SyntheticBar]:
        raise NotImplementedError(
            "VolumeTimeEngine (Engine B) is deferred to v2 per the v1 scope plan."
        )
