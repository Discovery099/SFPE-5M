"""Spec §6 Idea 1 — Dollar-Imbalance Synthetic Candles (Engine A).

Accumulate signed notional flow per source bar:
    signed_notional_t = sign(close_t - close_{t-1}) * volume_t * point_value

The synthetic candle closes when |cum_signed_notional| reaches a causal threshold
`theta_t`. We bootstrap `theta_t` from a rolling mean of |source-bar signed
notional| over the past `imbalance_window` bars, scaled by
`sqrt(expected_bars_per_session / target_bars_per_session)` (stopped-random-walk
first-hit scaling). See BLOCKERS.md §4 for rationale.

All calculations are session-aware and strictly causal.
"""
from __future__ import annotations

import math
from typing import List

import numpy as np
import pandas as pd

from .base import BaseEngine, SyntheticBar


class DollarImbalanceEngine(BaseEngine):
    name = "dollar_imbalance"

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        *,
        point_value: float,
        imbalance_window: int = 50,
        theta_mult: float = 1.0,
        target_bars_per_session: int = 8,
        expected_bars_per_session: int = 78,
        min_source_bars: int = 1,
        max_source_bars: int = 78,
        zero_sign_policy: str = "carry_positive",   # see BLOCKERS.md §3
    ) -> List[SyntheticBar]:
        n = len(df)
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        vols = df["volume"].values
        tprices = df["typical_price"].values
        sds = df["session_date"].values
        times = df["timestamp"]  # keep as tz-aware Series; access via .iloc

        # Pre-compute per-source-bar signed notional (causal).
        signed_src = np.zeros(n, dtype=float)
        for t in range(n):
            same_sess = (t > 0) and (sds[t] == sds[t - 1])
            if same_sess:
                diff = closes[t] - closes[t - 1]
                sgn = 1.0 if diff > 0 else (-1.0 if diff < 0 else (
                    1.0 if zero_sign_policy == "carry_positive" else -1.0))
            else:
                # session-open bar: use open->close direction
                sgn = 1.0 if closes[t] >= opens[t] else -1.0
            signed_src[t] = sgn * vols[t] * point_value

        abs_signed_s = pd.Series(np.abs(signed_src)).shift(1)
        rolling_mean = abs_signed_s.rolling(
            window=imbalance_window,
            min_periods=imbalance_window,
        ).mean()
        scale = math.sqrt(float(expected_bars_per_session)
                          / float(max(target_bars_per_session, 1)))
        theta_series = (theta_mult * rolling_mean * scale).values

        bars: List[SyntheticBar] = []
        i = 0
        while i < n:
            sd = sds[i]
            sess_end_idx = i
            while sess_end_idx + 1 < n and sds[sess_end_idx + 1] == sd:
                sess_end_idx += 1

            cur_start = i
            cum_signed = 0.0
            cum_notional = 0.0
            cum_vol = 0.0
            op = opens[i]
            hi = highs[i]
            lo = lows[i]

            for j in range(i, sess_end_idx + 1):
                # Replay the same sign convention used in signed_src so the cumulative
                # quantity in the engine and the theta series remain consistent.
                same_sess = (j > 0) and (sds[j] == sds[j - 1])
                if same_sess and j > cur_start:
                    diff = closes[j] - closes[j - 1]
                    sgn = 1.0 if diff > 0 else (-1.0 if diff < 0 else (
                        1.0 if zero_sign_policy == "carry_positive" else -1.0))
                else:
                    sgn = 1.0 if closes[j] >= opens[j] else -1.0
                notional_j = vols[j] * point_value
                cum_signed += sgn * notional_j
                cum_notional += vols[j] * tprices[j]
                cum_vol += vols[j]
                if highs[j] > hi:
                    hi = highs[j]
                if lows[j] < lo:
                    lo = lows[j]
                n_src = j - cur_start + 1

                theta_t = theta_series[j]
                budget_hit = (
                    (not math.isnan(theta_t))
                    and (theta_t > 0)
                    and (abs(cum_signed) >= theta_t)
                    and (n_src >= min_source_bars)
                )
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
                    cum_signed = 0.0
                    cum_notional = 0.0
                    cum_vol = 0.0
                    if cur_start <= sess_end_idx:
                        op = opens[cur_start]
                        hi = highs[cur_start]
                        lo = lows[cur_start]

            i = sess_end_idx + 1
        return bars
