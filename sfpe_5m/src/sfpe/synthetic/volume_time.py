"""Spec §6 Idea 2 — Volume-Time Synthetic Candles (Engine B).

Close a synthetic candle when accumulated source-bar volume reaches a per-session
target derived from the average prior `session_volume_lookback` RTH-session
totals, divided by `target_bars_per_session`.

All calculations are session-aware and strictly causal.
"""
from __future__ import annotations

import math
from typing import List

import numpy as np
import pandas as pd

from .base import BaseEngine, SyntheticBar


class VolumeTimeEngine(BaseEngine):
    name = "volume_time"

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        *,
        target_bars_per_session: int = 18,
        session_volume_lookback: int = 20,
        min_source_bars: int = 1,
        max_source_bars: int = 78,
    ) -> List[SyntheticBar]:
        # Per-session total volume.
        df_local = df[["session_date", "volume"]].copy()
        sess_vol = df_local.groupby("session_date")["volume"].sum()
        # Causal rolling mean of PRIOR K sessions (shift then rolling).
        sess_vol_shift = sess_vol.shift(1)
        sess_vol_mean = sess_vol_shift.rolling(
            window=session_volume_lookback,
            min_periods=session_volume_lookback,
        ).mean()
        v_target = sess_vol_mean / target_bars_per_session

        bars: List[SyntheticBar] = []
        n = len(df)
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        vols = df["volume"].values
        tprices = df["typical_price"].values
        sds = df["session_date"].values
        times = df["timestamp"]  # tz-aware

        i = 0
        while i < n:
            sd = sds[i]
            sess_end_idx = i
            while sess_end_idx + 1 < n and sds[sess_end_idx + 1] == sd:
                sess_end_idx += 1

            v_t = v_target.get(sd, np.nan)
            if pd.isna(v_t) or v_t <= 0:
                # Cold start: insufficient session history. Skip session output.
                i = sess_end_idx + 1
                continue

            cur_start = i
            cum_vol = 0.0
            cum_notional = 0.0
            cum_signed = 0.0
            op = opens[i]
            hi = highs[i]
            lo = lows[i]

            for j in range(i, sess_end_idx + 1):
                cum_vol += vols[j]
                cum_notional += vols[j] * tprices[j]
                # signed notional for downstream features (cheap to compute)
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

                budget_hit = (cum_vol >= v_t) and (n_src >= min_source_bars)
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
                        variance=0.0,
                        log_return=float(lr),
                        reason=reason,
                    ))
                    cur_start = j + 1
                    cum_vol = 0.0
                    cum_notional = 0.0
                    cum_signed = 0.0
                    if cur_start <= sess_end_idx:
                        op = opens[cur_start]
                        hi = highs[cur_start]
                        lo = lows[cur_start]

            i = sess_end_idx + 1
        return bars
