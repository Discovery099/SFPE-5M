"""Spec §6 Idea 4 — Range-Budget Synthetic Candles (Engine D).

STUB. Will be implemented in v2.
"""
from __future__ import annotations

from typing import List

import pandas as pd

from .base import BaseEngine, SyntheticBar


class RangeBudgetEngine(BaseEngine):
    name = "range_budget"

    def run(self, df: pd.DataFrame, symbol: str, **kwargs) -> List[SyntheticBar]:
        raise NotImplementedError(
            "RangeBudgetEngine (Engine D) is deferred to v2 per the v1 scope plan."
        )
