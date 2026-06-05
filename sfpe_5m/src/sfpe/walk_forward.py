"""Phase 6 walk-forward optimization (spec §13, fast protocol).

Fast protocol per owner spec:
  - 12-month train window
  - 3-month validation window
  - 3-month test (out-of-sample) window
  - 3-month step  (compute reduction vs the 1-month step originally listed —
                    documented in BLOCKERS §44).

Per-instrument optimisation, no portfolio aggregation at this stage.

Search grid (reduced, see BLOCKERS §44):
  - structural_buffer_atr_mult ∈ {0.5, 1.0, 2.0}
  - projection_hold_mult       ∈ {1.5, 3.0}
  - tp1_partial_fraction       ∈ {0.0, 1.0}   (extremes only)
  - min_confidence             ∈ {0.50, 0.65}
  - min_engines_agree          fixed at 3
  - risk_per_trade             fixed at 0.005

Composite score weights are documented in BLOCKERS §44.

Outputs to `reports/v1_6/`:
  per_instrument__<SYM>__folds.csv  -- one row per (fold, OOS).
  per_instrument__<SYM>__selected.csv  -- one row per fold with chosen params.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Iterable, Optional

import math
import numpy as np
import pandas as pd
import yaml

from sfpe.data.calendar import load_calendars
from sfpe.data.loader import load_instrument_csv
from sfpe.backtest import (
    BASELINES, BacktestParams, EventEngine, fixed_tick_cost,
    deflated_sharpe, pbo_score, compute_metrics, trades_to_dataframe,
    recompute_trade_eligibility, EligibilityParams,
)
from sfpe.backtest.signals import StructuralStopParams
from sfpe.backtest.runner import build_roll_skip_idxs


# ---------------------------------------------------------------------------
# Search space (reduced — see BLOCKERS §44).
# ---------------------------------------------------------------------------
GRID = dict(
    structural_buffer_atr_mult=(0.5, 1.0, 2.0),
    projection_hold_mult=(1.5, 3.0),
    tp1_partial_fraction=(0.5,),             # fixed — Phase 5.5 showed partial rarely fires at risk=0.005
    min_confidence=(0.50, 0.65),
)
# Fixed parameters (held at v1.5 defaults — keeps fitted dimension small):
GRID_FIXED = dict(
    min_engines_agree=3,
    risk_per_trade=0.005,
)

# Fold geometry (months).
FOLD_TRAIN_M = 12
FOLD_VAL_M = 3
FOLD_TEST_M = 3
FOLD_STEP_M = 6                              # 6-month step -> ~7 folds across 60 months


@dataclass
class FoldSpec:
    fold_idx: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    val_start: pd.Timestamp
    val_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def _months_offset(t: pd.Timestamp, months: int) -> pd.Timestamp:
    return (t + pd.DateOffset(months=months)).normalize()


def generate_folds(*, sample_start: pd.Timestamp, sample_end: pd.Timestamp) -> list[FoldSpec]:
    """Generate anchored walk-forward folds.

    Returns list of FoldSpec each spanning train+val+test, stepping FOLD_STEP_M
    months forward.
    """
    folds: list[FoldSpec] = []
    fold_idx = 0
    cursor = sample_start
    while True:
        train_end = _months_offset(cursor, FOLD_TRAIN_M)
        val_end = _months_offset(train_end, FOLD_VAL_M)
        test_end = _months_offset(val_end, FOLD_TEST_M)
        if test_end > sample_end:
            break
        folds.append(FoldSpec(
            fold_idx=fold_idx,
            train_start=cursor, train_end=train_end,
            val_start=train_end, val_end=val_end,
            test_start=val_end, test_end=test_end,
        ))
        fold_idx += 1
        cursor = _months_offset(cursor, FOLD_STEP_M)
    return folds


# ---------------------------------------------------------------------------
# Composite score (spec §10.4 starting weights — documented BLOCKERS §44).
# ---------------------------------------------------------------------------
def composite_score(metrics: dict) -> float:
    """Higher is better."""
    n = int(metrics.get("n_trades", 0))
    if n == 0:
        return -1e9
    sharpe = float(metrics.get("sharpe", 0.0))
    pf = float(metrics.get("profit_factor", 0.0))
    if not math.isfinite(pf):
        pf_term = 1.0
    else:
        pf_term = max(0.0, pf - 1.0)
    n_norm = min(1.0, n / 30.0)
    max_dd_pct = abs(float(metrics.get("max_drawdown_pct", 0.0)) or 0.0)
    win = float(metrics.get("win_rate", 0.0))
    win_loss_proxy = 1.0 - max(0.0, 0.5 - win)
    return (0.40 * sharpe
            + 0.30 * pf_term
            + 0.15 * n_norm
            + 0.10 * win_loss_proxy
            - 0.05 * max_dd_pct)


# ---------------------------------------------------------------------------
# Per-fold backtest under a fixed config.
# ---------------------------------------------------------------------------
def slice_by_date_range(*, source_df: pd.DataFrame, signal_df: pd.DataFrame,
                         start: pd.Timestamp, end: pd.Timestamp,
                         ) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Return (sliced_source, sliced_signals, slice_offset) constrained to
    [start, end). The offset is the source_df.index value of the first
    sliced row -- used to translate roll-skip indices into the sliced frame.
    """
    ts = source_df["timestamp"]
    mask = (ts >= start) & (ts < end)
    sliced = source_df[mask].copy()
    if sliced.empty:
        return sliced, signal_df.iloc[0:0].copy(), 0
    offset = int(sliced.index[0])
    src = sliced.reset_index(drop=True)
    sig = signal_df.iloc[mask.values].reset_index(drop=True)
    return src, sig, offset


def run_fold_config(
    *, source_slice: pd.DataFrame, signals_slice: pd.DataFrame,
    inst_cfg: dict,
    structural_buffer: float, projection_hold_mult: float,
    tp1_partial: float, conf: float,
    risk_per_trade: float = 0.005,
    roll_skip_local_idxs: set[int],
) -> dict:
    """Run a single backtest on the sliced data with given params; return metrics dict."""
    if source_slice.empty:
        return dict(n_trades=0, composite=-1e9)
    p = BacktestParams(
        starting_equity=100_000.0,
        risk_per_trade=risk_per_trade,
        slippage_mult=1.0, slippage_ticks=1.0,
        use_projection_exits=True,
        tp1_partial_fraction=tp1_partial,
        fallback_buffer_atr_mult=structural_buffer,
        projection_hold_mult=projection_hold_mult,
        projection_hold_fallback=12,
    )
    # The signals' structural_stop_long/short were precomputed at buffer=0.5;
    # we need them recomputed for the current buffer. Recompute on-the-fly is
    # too slow per fold/config — instead, recompute the anchor by adding back
    # the old 0.5×ATR buffer, then subtracting the new buffer×ATR. We do this
    # vectorised once at engine call by passing the recomputed slice.
    # In practice the engine's stop logic uses the `structural_stop_long/short`
    # columns directly + the `fallback_buffer_atr_mult` (for non-override rows).
    # To keep this clean, we re-derive structural stops from the original anchor
    # which we store in column `structural_anchor` in the signal frame.
    sig = signals_slice.copy()
    if "structural_anchor" in sig.columns:
        anchor = sig["structural_anchor"].values
        atr = source_slice["atr_20"].values
        buf = structural_buffer * atr
        sig["structural_stop_long"] = anchor - buf
        sig["structural_stop_short"] = anchor + buf
        # has_structural_stop: True where anchor is finite.
        sig["has_structural_stop"] = np.isfinite(anchor)
    engine = EventEngine(p)
    res = engine.run(
        source_df=source_slice, signals_df=sig, inst_cfg=inst_cfg,
        cost_fn=fixed_tick_cost, cost_model_name="fixed_tick",
        roll_skip_idxs=roll_skip_local_idxs,
    )
    df_t = trades_to_dataframe(res.trades)
    m = compute_metrics(df_t)
    m["composite"] = composite_score(m)
    return m


# ---------------------------------------------------------------------------
# Top-level per-instrument optimiser.
# ---------------------------------------------------------------------------
def precompute_signals_at_confidence(
    *, ensemble_csv: Path, source_df: pd.DataFrame,
    regime_csv: Path, absorption_csv: Path, vacuum_csv: Path, tpo_csv: Path,
    latest_entry_time_et: str, conf: float,
) -> pd.DataFrame:
    """Recompute signals at a given confidence and INJECT the structural anchor
    column so per-fold runs can re-derive structural stops for any buffer."""
    sig = recompute_trade_eligibility(
        ensemble_csv=ensemble_csv, source_df=source_df, regime_csv=regime_csv,
        absorption_csv=absorption_csv, vacuum_csv=vacuum_csv, tpo_csv=tpo_csv,
        params=EligibilityParams(latest_entry_time_et=latest_entry_time_et,
                                   min_confidence=conf),
        structural_stop_params=StructuralStopParams(structural_buffer_atr_mult=0.5,
                                                      fallback_buffer_atr_mult=0.5),
    )
    # Recover the anchor from structural_stop_long + 0.5*ATR (long-side rec).
    atr = source_df["atr_20"].astype(float).values
    sl = sig["structural_stop_long"].astype(float).values
    anchor = np.where(np.isfinite(sl), sl + 0.5 * atr, np.nan)
    sig["structural_anchor"] = anchor
    return sig


def walk_forward_one_instrument(
    *, symbol: str, repo: Path,
) -> dict:
    """Returns dict with per-fold per-config in-sample + OOS results."""
    instruments_yaml = repo / "config" / "instruments.yaml"
    calendars_yaml = repo / "config" / "session_calendars.yaml"
    cfg = yaml.safe_load(instruments_yaml.read_text())
    cals = load_calendars(calendars_yaml)
    ic = cfg["instruments"][symbol]
    cal = cals[ic["calendar"]]
    inst_cfg = dict(symbol=symbol, family=ic["family"],
                    point_value=float(ic["point_value"]),
                    tick_size=float(ic["tick_size"]),
                    tick_value=float(ic["tick_value"]))
    source_df = load_instrument_csv(repo / ic["file"], cal)

    # Roll-skip indices over the FULL source frame.
    roll_skip_full, _ = build_roll_skip_idxs(
        source_df=source_df,
        roll_candidates_csv=repo / "reports" / "v1_4_roll_candidates.csv",
        symbol=symbol, mode="v1_4",
    )

    # Precompute one signal frame per confidence.
    ensemble_csv = repo / "features" / f"projection_ensemble__{symbol}.csv"
    regime_csv = repo / "features" / f"regime__{symbol}.csv"
    absorption_csv = repo / "features" / f"absorption__{symbol}.csv"
    vacuum_csv = repo / "features" / f"vacuum__{symbol}.csv"
    tpo_csv = repo / "features" / f"tpo__{symbol}.csv"
    sigs_by_conf = {
        c: precompute_signals_at_confidence(
            ensemble_csv=ensemble_csv, source_df=source_df,
            regime_csv=regime_csv, absorption_csv=absorption_csv,
            vacuum_csv=vacuum_csv, tpo_csv=tpo_csv,
            latest_entry_time_et=ic["latest_entry_time"], conf=c,
        )
        for c in GRID["min_confidence"]
    }

    sample_start = source_df["timestamp"].min().normalize()
    sample_end = source_df["timestamp"].max().normalize()
    folds = generate_folds(sample_start=sample_start, sample_end=sample_end)

    fold_results: list[dict] = []           # one row per (fold, config) on val+test
    selected_per_fold: list[dict] = []      # one row per fold with the chosen config

    # Collect OOS perfs per (variant_key) across folds for PBO.
    perfs_by_variant: dict[str, list[float]] = {}

    for fold in folds:
        # For each config combo, compute in-sample (train+val combined) metric.
        # Then take best by composite and apply to OOS test.
        in_sample_results: list[dict] = []
        for combo in product(
            GRID["structural_buffer_atr_mult"],
            GRID["projection_hold_mult"],
            GRID["tp1_partial_fraction"],
            GRID["min_confidence"],
        ):
            buf, hold_mult, partial, conf = combo
            variant_key = f"buf={buf}|hold={hold_mult}|partial={partial}|conf={conf}"
            sig_full = sigs_by_conf[conf]
            # Map roll-skip indices into the train slice's local index space.
            # In-sample = train+val concatenated.
            src_tr, sig_tr, off_tr = slice_by_date_range(
                source_df=source_df, signal_df=sig_full,
                start=fold.train_start, end=fold.val_end,
            )
            if src_tr.empty:
                continue
            tr_local_skip = {i - off_tr for i in roll_skip_full
                              if off_tr <= i < off_tr + len(src_tr)}
            m_in = run_fold_config(
                source_slice=src_tr, signals_slice=sig_tr,
                inst_cfg=inst_cfg,
                structural_buffer=buf, projection_hold_mult=hold_mult,
                tp1_partial=partial, conf=conf,
                roll_skip_local_idxs=tr_local_skip,
            )
            in_sample_results.append(dict(variant_key=variant_key,
                                           buf=buf, hold_mult=hold_mult,
                                           partial=partial, conf=conf,
                                           in_n_trades=m_in.get("n_trades", 0),
                                           in_pf=m_in.get("profit_factor", float("nan")),
                                           in_sharpe=m_in.get("sharpe", 0.0),
                                           in_net=m_in.get("net_profit", 0.0),
                                           in_winrate=m_in.get("win_rate", 0.0),
                                           in_composite=m_in.get("composite", -1e9),
                                           fold_idx=fold.fold_idx))
        if not in_sample_results:
            continue
        # Pick best in-sample.
        best = max(in_sample_results, key=lambda r: r["in_composite"])
        # OOS test under best config.
        sig_full = sigs_by_conf[best["conf"]]
        src_te, sig_te, off_te = slice_by_date_range(
            source_df=source_df, signal_df=sig_full,
            start=fold.test_start, end=fold.test_end,
        )
        te_local_skip = {i - off_te for i in roll_skip_full
                         if off_te <= i < off_te + len(src_te)}
        m_oos = run_fold_config(
            source_slice=src_te, signals_slice=sig_te,
            inst_cfg=inst_cfg,
            structural_buffer=best["buf"], projection_hold_mult=best["hold_mult"],
            tp1_partial=best["partial"], conf=best["conf"],
            roll_skip_local_idxs=te_local_skip,
        )

        selected_per_fold.append(dict(
            symbol=symbol,
            fold_idx=fold.fold_idx,
            train_start=str(fold.train_start.date()),
            train_end=str(fold.train_end.date()),
            val_end=str(fold.val_end.date()),
            test_start=str(fold.test_start.date()),
            test_end=str(fold.test_end.date()),
            sel_buf=best["buf"], sel_hold_mult=best["hold_mult"],
            sel_partial=best["partial"], sel_conf=best["conf"],
            in_composite=best["in_composite"], in_n_trades=best["in_n_trades"],
            in_pf=best["in_pf"], in_sharpe=best["in_sharpe"],
            in_net=best["in_net"], in_winrate=best["in_winrate"],
            oos_n_trades=m_oos.get("n_trades", 0),
            oos_pf=m_oos.get("profit_factor", float("nan")),
            oos_sharpe=m_oos.get("sharpe", 0.0),
            oos_net=m_oos.get("net_profit", 0.0),
            oos_winrate=m_oos.get("win_rate", 0.0),
            oos_composite=m_oos.get("composite", -1e9),
        ))
        # Record OOS perfs per variant_key for PBO.
        for r in in_sample_results:
            key = r["variant_key"]
            # Re-run OOS for THIS variant to record its OOS perf (needed for PBO).
            # Optimisation: skip if OOS slice empty.
            sig_full = sigs_by_conf[r["conf"]]
            src_te2, sig_te2, off_te2 = slice_by_date_range(
                source_df=source_df, signal_df=sig_full,
                start=fold.test_start, end=fold.test_end,
            )
            if src_te2.empty:
                continue
            te2_skip = {i - off_te2 for i in roll_skip_full
                        if off_te2 <= i < off_te2 + len(src_te2)}
            m_v = run_fold_config(
                source_slice=src_te2, signals_slice=sig_te2,
                inst_cfg=inst_cfg,
                structural_buffer=r["buf"], projection_hold_mult=r["hold_mult"],
                tp1_partial=r["partial"], conf=r["conf"],
                roll_skip_local_idxs=te2_skip,
            )
            perfs_by_variant.setdefault(key, []).append(float(m_v.get("composite", 0.0)))
            fold_results.append(dict(
                **r,
                oos_n_trades=m_v.get("n_trades", 0),
                oos_pf=m_v.get("profit_factor", float("nan")),
                oos_sharpe=m_v.get("sharpe", 0.0),
                oos_net=m_v.get("net_profit", 0.0),
                oos_winrate=m_v.get("win_rate", 0.0),
                oos_composite=m_v.get("composite", -1e9),
            ))

    pbo = pbo_score(perfs_by_variant) if perfs_by_variant else float("nan")
    n_trials = len(perfs_by_variant)
    # DSR for the SELECTED OOS sharpe average across folds.
    oos_sharpes = [s["oos_sharpe"] for s in selected_per_fold
                   if math.isfinite(s.get("oos_sharpe", 0.0))]
    mean_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
    dsr = deflated_sharpe(mean_oos_sharpe, n_trials=n_trials)
    return dict(
        symbol=symbol,
        n_folds=len(selected_per_fold),
        n_trials=n_trials,
        pbo=pbo,
        deflated_sharpe=dsr,
        mean_oos_sharpe=mean_oos_sharpe,
        fold_results=fold_results,
        selected_per_fold=selected_per_fold,
    )


def aggregate_selected_params_for_export(selected_per_fold: list[dict]) -> dict:
    """Pick the per-instrument "final" parameters for Pine export.

    Strategy: take the mode of each parameter across folds; if no mode, take the
    median. This is more robust than the last-fold's selection (which is biased
    by recency).
    """
    if not selected_per_fold:
        return dict(buf=0.5, hold_mult=1.5, partial=0.5, conf=0.65)
    df = pd.DataFrame(selected_per_fold)
    def _mode_or_median(col: str, fallback):
        vc = df[col].value_counts()
        if vc.empty:
            return fallback
        top_count = vc.iloc[0]
        # Mode if it has a clear plurality (>= 1/3 of folds).
        if top_count >= max(2, len(df) // 3):
            return float(vc.index[0])
        return float(df[col].median())
    return dict(
        buf=_mode_or_median("sel_buf", 0.5),
        hold_mult=_mode_or_median("sel_hold_mult", 1.5),
        partial=_mode_or_median("sel_partial", 0.5),
        conf=_mode_or_median("sel_conf", 0.65),
    )
