"""Spec §6 Idea 3 — Vol-Budget Synthetic Candles (Engine C).

Close a synthetic candle when accumulated within-bar realized variance reaches a
session-derived target. The target is the average per-RTH-session Parkinson
variance over the prior `variance_lookback_sessions`, divided by
`target_bars_per_session`, optionally scaled by `sigma_mult`.

All calculations are session-aware and strictly causal.
"""
from __future__ import annotations

import math
from typing import List

import numpy as np
import pandas as pd

from .base import BaseEngine, SyntheticBar, parkinson_variance


class VolBudgetEngine(BaseEngine):
    name = "vol_budget"

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        *,
        target_bars_per_session: int = 6,
        variance_lookback_sessions: int = 20,
        sigma_mult: float = 1.0,
        variance_proxy: str = "parkinson",   # or "close_to_close"
        min_source_bars: int = 1,
        max_source_bars: int = 78,
    ) -> List[SyntheticBar]:
        if variance_proxy not in ("parkinson", "close_to_close"):
            raise ValueError(f"unknown variance_proxy {variance_proxy!r}")

        # Per-source-bar variance contribution.
        if variance_proxy == "parkinson":
            var_arr = np.array([parkinson_variance(h, lo_)
                                for h, lo_ in zip(df["high"].values, df["low"].values)],
                               dtype=float)
        else:
            # close-to-close variance contribution; session-boundary aware.
            lr = df["log_return"].values
            var_arr = np.where(np.isnan(lr), 0.0, lr ** 2)

        # Sum per session, then take rolling mean of PRIOR K sessions (causal shift).
        df_local = df[["session_date"]].copy()
        df_local["_var"] = var_arr
        sess_var = df_local.groupby("session_date")["_var"].sum().rename("sess_var")
        # Use a SHIFTED rolling mean so the target for session S uses only S-K..S-1.
        sess_var_shift = sess_var.shift(1)
        sess_var_mean = sess_var_shift.rolling(
            window=variance_lookback_sessions,
            min_periods=variance_lookback_sessions,
        ).mean()
        target_var = (sess_var_mean / target_bars_per_session) * sigma_mult

        bars: List[SyntheticBar] = []
        n = len(df)
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        vols = df["volume"].values
        tprices = df["typical_price"].values
        sds = df["session_date"].values
        times = df["timestamp"]  # keep as tz-aware Series; access via .iloc

        i = 0
        while i < n:
            sd = sds[i]
            sess_end_idx = i
            while sess_end_idx + 1 < n and sds[sess_end_idx + 1] == sd:
                sess_end_idx += 1

            sigma2_target = target_var.get(sd, np.nan)
            if pd.isna(sigma2_target) or sigma2_target <= 0:
                # Insufficient history for this session: skip session output entirely.
                i = sess_end_idx + 1
                continue

            cur_start = i
            cum_var = 0.0
            cum_vol = 0.0
            cum_notional = 0.0
            cum_signed = 0.0
            op = opens[i]
            hi = highs[i]
            lo = lows[i]

            for j in range(i, sess_end_idx + 1):
                if variance_proxy == "parkinson":
                    cum_var += parkinson_variance(highs[j], lows[j])
                else:
                    cum_var += var_arr[j]
                cum_vol += vols[j]
                notional_j = vols[j] * tprices[j]
                cum_notional += notional_j
                if j == cur_start:
                    sgn = 1.0 if closes[j] >= opens[j] else -1.0
                else:
                    diff = closes[j] - closes[j - 1]
                    sgn = 1.0 if diff > 0 else (-1.0 if diff < 0 else 1.0)
                cum_signed += sgn * notional_j
                if highs[j] > hi:
                    hi = highs[j]
                if lows[j] < lo:
                    lo = lows[j]
                n_src = j - cur_start + 1

                budget_hit = (cum_var >= sigma2_target) and (n_src >= min_source_bars)
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
                        variance=float(cum_var),
                        log_return=float(lr),
                        reason=reason,
                    ))
                    cur_start = j + 1
                    cum_var = 0.0
                    cum_vol = 0.0
                    cum_notional = 0.0
                    cum_signed = 0.0
                    if cur_start <= sess_end_idx:
                        op = opens[cur_start]
                        hi = highs[cur_start]
                        lo = lows[cur_start]

            i = sess_end_idx + 1
        return bars
