"""Spec §6 Idea 4 — Range-Budget Synthetic Candles (Engine D).

Close a synthetic candle when its accumulated price range (high - low since
synthetic open) reaches `range_k * ATR_at_synthetic_open`. ATR is the causal,
session-aware ATR_20 derived in the loader.

All calculations are session-aware and strictly causal.
"""
from __future__ import annotations

import math
from typing import List

import pandas as pd

from .base import BaseEngine, SyntheticBar


class RangeBudgetEngine(BaseEngine):
    name = "range_budget"

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        *,
        range_k: float = 1.0,
        min_source_bars: int = 1,
        max_source_bars: int = 78,
    ) -> List[SyntheticBar]:
        bars: List[SyntheticBar] = []
        n = len(df)
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        vols = df["volume"].values
        tprices = df["typical_price"].values
        sds = df["session_date"].values
        atrs = df["atr_20"].values
        times = df["timestamp"]

        i = 0
        while i < n:
            sd = sds[i]
            sess_end_idx = i
            while sess_end_idx + 1 < n and sds[sess_end_idx + 1] == sd:
                sess_end_idx += 1

            cur_start = i
            atr_at_open = atrs[cur_start]
            cum_vol = 0.0
            cum_notional = 0.0
            cum_signed = 0.0
            op = opens[i]
            hi = highs[i]
            lo = lows[i]

            for j in range(i, sess_end_idx + 1):
                cum_vol += vols[j]
                cum_notional += vols[j] * tprices[j]
                if j == cur_start:
                    sgn = 1.0 if closes[j] >= opens[j] else -1.0
                else:
                    diff = closes[j] - closes[j - 1]
                    sgn = 1.0 if diff > 0 else (-1.0 if diff < 0 else 1.0)
                cum_signed += sgn * vols[j] * tprices[j]
                if highs[j] > hi:
                    hi = highs[j]
                if lows[j] < lo:
                    lo = lows[j]
                n_src = j - cur_start + 1

                synth_range = hi - lo
                threshold = range_k * atr_at_open if atr_at_open and atr_at_open > 0 else float("inf")
                budget_hit = (synth_range >= threshold) and (n_src >= min_source_bars)
                max_hit = n_src >= max_source_bars
                session_end_hit = (j == sess_end_idx)

                if budget_hit or max_hit or session_end_hit:
                    cl = closes[j]
                    lr = math.log(cl / op) if (op > 0 and cl > 0) else float("nan")
                    reason = "budget" if budget_hit else ("max_bars" if max_hit else "session_end")
                    bars.append(SyntheticBar(
                        engine=self.name,
                        symbol=symbol,
                        session_date=sd,
                        start_idx=cur_start,
                        end_idx=j,
                        open_time=times.iloc[cur_start],
                        close_time=times.iloc[j],
                        open=float(op), high=float(hi), low=float(lo), close=float(cl),
                        volume=float(cum_vol),
                        n_source_bars=int(n_src),
                        notional=float(cum_notional),
                        signed_notional=float(cum_signed),
                        variance=float(synth_range),  # store synthetic range in variance slot
                        log_return=float(lr),
                        reason=reason,
                    ))
                    cur_start = j + 1
                    if cur_start <= sess_end_idx:
                        atr_at_open = atrs[cur_start]
                        op = opens[cur_start]
                        hi = highs[cur_start]
                        lo = lows[cur_start]
                    cum_vol = 0.0
                    cum_notional = 0.0
                    cum_signed = 0.0

            i = sess_end_idx + 1
        return bars
