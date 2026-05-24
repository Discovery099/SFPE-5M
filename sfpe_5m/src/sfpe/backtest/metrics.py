"""Spec §9.3 metrics + spec §12 baselines comparison helpers.

Includes Bailey-Lopez de Prado Deflated Sharpe (DSR) approximation.
PBO is computed via combinatorial cross-validation in `runner.py` over the set
of variants we run.
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd


def compute_metrics(trades_df: pd.DataFrame, *, starting_equity: float = 100_000.0) -> dict:
    if trades_df.empty:
        return dict(n_trades=0)
    closed = trades_df[trades_df["exit_reason"] != "open"].copy()
    if closed.empty:
        return dict(n_trades=0)
    pnl = closed["net_pnl"].astype(float)
    n = len(pnl)
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(-pnl[pnl < 0].sum())
    net_profit = float(pnl.sum())
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    win_rate = float(len(wins) / n) if n else 0.0
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    expectancy = float(pnl.mean())

    # Equity curve (cumulative net_pnl).
    eq = starting_equity + pnl.cumsum()
    peak = eq.cummax()
    dd = (eq - peak)
    max_dd = float(dd.min())
    max_dd_pct = float((dd / peak.replace(0, np.nan)).min())

    # Returns per trade (relative to starting equity).
    r = pnl / starting_equity
    if r.std(ddof=0) > 0:
        sharpe = float(r.mean() / r.std(ddof=0) * math.sqrt(252))
    else:
        sharpe = 0.0
    downside = r[r < 0]
    sortino = float(r.mean() / downside.std(ddof=0) * math.sqrt(252)) if len(downside) and downside.std(ddof=0) > 0 else 0.0
    calmar = float(net_profit / abs(max_dd)) if max_dd < 0 else float("inf") if net_profit > 0 else 0.0

    avg_bars = float(closed["bars_held"].mean()) if "bars_held" in closed else 0.0
    avg_mae = float(closed["mae"].mean()) if "mae" in closed else 0.0
    avg_mfe = float(closed["mfe"].mean()) if "mfe" in closed else 0.0

    # Consecutive wins/losses
    wins_mask = (pnl > 0).astype(int).values
    max_consec_win = _max_streak(wins_mask, 1)
    max_consec_loss = _max_streak(wins_mask, 0)

    # Trades per month
    if "entry_time" in closed.columns and len(closed):
        et = pd.to_datetime(closed["entry_time"])
        months = et.dt.to_period("M").nunique()
        trades_per_month = float(n / months) if months > 0 else 0.0
        # monthly concentration
        monthly_pnl = pnl.groupby(et.dt.to_period("M").values).sum()
        if net_profit > 0:
            top_month_share = float(monthly_pnl.max() / net_profit) if monthly_pnl.max() > 0 else 0.0
        else:
            top_month_share = 0.0
    else:
        trades_per_month = 0.0
        top_month_share = 0.0

    # Deflated Sharpe Ratio (approx, based on Bailey-Lopez de Prado simplified form).
    # If only one trial, dsr ~ sharpe. For multiple trials see runner-level.
    dsr = sharpe   # simplified for single-config evaluation; runner adjusts.

    return dict(
        n_trades=int(n),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_profit=net_profit,
        profit_factor=pf,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy=expectancy,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        avg_bars_held=avg_bars,
        avg_mae=avg_mae,
        avg_mfe=avg_mfe,
        max_consec_win=max_consec_win,
        max_consec_loss=max_consec_loss,
        trades_per_month=trades_per_month,
        top_month_share=top_month_share,
        deflated_sharpe=dsr,
    )


def _max_streak(arr, target_val: int) -> int:
    best = 0
    cur = 0
    for v in arr:
        if v == target_val:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return int(best)


def regime_breakdown(trades_df: pd.DataFrame, col: str) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame()
    g = trades_df.groupby(col).agg(
        n=("net_pnl", "size"),
        net=("net_pnl", "sum"),
        win_rate=("net_pnl", lambda s: float((s > 0).mean())),
        avg=("net_pnl", "mean"),
    ).round(4)
    return g.sort_values("net", ascending=False)


def deflated_sharpe(observed_sharpe: float, n_trials: int, sample_var_skew: float = 0.0,
                    sample_var_kurt: float = 3.0) -> float:
    """Simplified DSR. Penalizes observed sharpe for number of trials searched.
    See Bailey & Lopez de Prado 2014. We use a Bonferroni-style adjustment for
    the trials count, the simplest version that respects the intent.
    """
    if n_trials <= 1:
        return float(observed_sharpe)
    # Bonferroni adjustment factor for n_trials
    z_alpha = 1.96  # 95% conf single-tail correction
    adj = z_alpha * math.sqrt(2 * math.log(n_trials))
    # DSR = observed - adjustment / sqrt(N), but we don't have N; approx with n_trials
    return float(observed_sharpe - adj / max(math.sqrt(n_trials), 1.0))


def pbo_score(perfs_by_variant: dict[str, list[float]]) -> float:
    """Probability of backtest overfitting via combinatorial cross-validation.

    perfs_by_variant: {variant_name: list of out-of-sample perfs over K folds}
    Returns the share of folds where the in-sample-best variant has below-median
    out-of-sample performance.  See Bailey, Borwein, Lopez de Prado, Zhu 2017.

    With only a couple of variants this is a coarse measure; we report it for
    spec compliance and to be revisited under Phase-6 walk-forward.
    """
    if not perfs_by_variant:
        return float("nan")
    variant_names = list(perfs_by_variant.keys())
    K = min(len(v) for v in perfs_by_variant.values())
    if K < 2:
        return float("nan")
    overfit_events = 0
    total = 0
    for hold_out_fold in range(K):
        in_sample = {v: [perfs_by_variant[v][k] for k in range(K) if k != hold_out_fold]
                     for v in variant_names}
        # Best variant in-sample (max of mean perf).
        is_means = {v: float(np.mean(in_sample[v])) for v in variant_names}
        best = max(is_means, key=lambda k: is_means[k])
        # Out-of-sample perf of that variant.
        oos = perfs_by_variant[best][hold_out_fold]
        # Median of all variants OOS in the held-out fold
        oos_all = [perfs_by_variant[v][hold_out_fold] for v in variant_names]
        med = float(np.median(oos_all))
        if oos < med:
            overfit_events += 1
        total += 1
    return float(overfit_events / total) if total else float("nan")
