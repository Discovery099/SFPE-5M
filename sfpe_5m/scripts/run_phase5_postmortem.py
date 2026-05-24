"""Phase 5.5 Option C — Forensic post-mortem on the v1.5 trade ledger.

Per owner instruction (2026-05-24), this is FORENSIC ANALYSIS only:
no new backtest runs, no parameter tuning, no optimization.  The script
re-derives per-trade entry context by running the v1.5 backtest at the
primary variant (conf=0.65, fixed_tick, 1× slip) and then replays each
trade against the v1.5 SOURCE BARS under counterfactual exit semantics.

Counterfactuals (computed per-trade on the existing trajectory; no
re-sizing of contracts -- we want to isolate the exit-semantics effect):
  - W1: structural_buffer_atr_mult = 1.0  (vs original 0.5), same max_bars_hold.
  - W2: structural_buffer_atr_mult = 2.0  AND  proj_hold_mult = 3.0
        (vs original 1.5  ->  max_bars_hold becomes 2× the original).

Outcome categories per counterfactual:
  - tp2_reach        : TP2 hit before counterfactual stop within the hold window.
  - stop_out         : counterfactual stop hit before TP2 within the hold window.
  - time_stop        : neither hit within the hold window (close at end of window).
  - session_end      : session boundary closed the trade first.

Projection durability per stopped trade:
  - durability_window = 3 × original projection_hold_mult × proj_completion_median
                      = 3 × original max_bars_hold (since original = ceil(med × 1.5))
  - Did the high/low of any bar within the durability window touch the projected
    close zone [projected_close_low, projected_close_high]?
  - Did it specifically reach TP2 (high>=TP2 for long, low<=TP2 for short)?

Outputs:
  reports/v1_5_phase5_postmortem.md           -- aggregate tables + verdict.
  reports/v1_5_phase5_postmortem_trades.csv   -- per-trade ledger w/ counterfactuals.
  reports/v1_5_phase5_postmortem_winners.csv  -- TP2 winners feature profile.
"""
from __future__ import annotations

import argparse
import sys
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from loguru import logger

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.data.calendar import load_calendars
from sfpe.data.loader import load_instrument_csv
from sfpe.backtest import (
    BacktestParams, EventEngine, fixed_tick_cost,
    recompute_trade_eligibility, EligibilityParams,
)
from sfpe.backtest.signals import StructuralStopParams
from sfpe.backtest.runner import build_roll_skip_idxs


PRIMARY_BUFFER = 0.5          # original structural / fallback buffer used in v1.5
PRIMARY_HOLD_MULT = 1.5        # original projection_hold_mult used in v1.5


# ---------------------------------------------------------------------------
# Replay engine (pure NumPy, conservative stop-first, session-end aware).
# ---------------------------------------------------------------------------
def replay_trade(
    *,
    entry_idx: int,
    direction: int,
    stop_price: float,
    target_price: float,
    max_bars_hold: int,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    session_dates: np.ndarray,
) -> dict:
    """Walk forward from entry_idx; return first-touch exit info.

    Returns dict with: exit_idx, exit_reason ('tp2'/'stop'/'session_end'/'time_stop'),
    exit_price (the fill price hypothetical, before slip — that's an exit-level
    constant we don't move under counterfactual analysis).
    """
    n = len(highs)
    entry_sd = session_dates[entry_idx]
    end_idx = min(entry_idx + max_bars_hold, n - 1)
    for i in range(entry_idx, end_idx + 1):
        hi, lo = highs[i], lows[i]
        if direction > 0:
            hit_stop = lo <= stop_price
            hit_tp = hi >= target_price
        else:
            hit_stop = hi >= stop_price
            hit_tp = lo <= target_price
        # Conservative stop-first (spec §8.3).
        if hit_stop:
            return dict(exit_idx=i, exit_reason="stop", exit_price=float(stop_price))
        if hit_tp:
            return dict(exit_idx=i, exit_reason="tp2", exit_price=float(target_price))
        # Session-end check (force-flatten at last bar of session).
        if i < n - 1 and session_dates[i + 1] != entry_sd:
            return dict(exit_idx=i, exit_reason="session_end",
                        exit_price=float(closes[i]))
    # Time-stop (no first-touch within window).
    return dict(exit_idx=end_idx, exit_reason="time_stop", exit_price=float(closes[end_idx]))


def projection_durability(
    *,
    entry_idx: int,
    direction: int,
    target_price: float,
    proj_close_low: float,
    proj_close_high: float,
    durability_window: int,
    highs: np.ndarray,
    lows: np.ndarray,
    session_dates: np.ndarray,
) -> dict:
    """Within `durability_window` bars (capped at session boundary), check
    whether price ever (a) reached TP2 or (b) visited the projected close zone.
    """
    n = len(highs)
    end_idx = min(entry_idx + durability_window, n - 1)
    visited_zone = False
    reached_tp2 = False
    tp2_idx = None
    entry_sd = session_dates[entry_idx]
    for i in range(entry_idx, end_idx + 1):
        hi, lo = highs[i], lows[i]
        # Zone visit: any overlap between [lo, hi] and [proj_close_low, proj_close_high]
        zlo, zhi = (proj_close_low, proj_close_high) if proj_close_low <= proj_close_high \
                   else (proj_close_high, proj_close_low)
        if (hi >= zlo) and (lo <= zhi):
            visited_zone = True
        if direction > 0 and hi >= target_price:
            if not reached_tp2:
                tp2_idx = i
            reached_tp2 = True
        elif direction < 0 and lo <= target_price:
            if not reached_tp2:
                tp2_idx = i
            reached_tp2 = True
        # Allow crossing session boundaries within the durability window so we
        # genuinely test "ever verified given more time" — durability is not
        # constrained to the original session.
    return dict(visited_zone=visited_zone, reached_tp2=reached_tp2,
                tp2_first_idx=tp2_idx)


# ---------------------------------------------------------------------------
# Per-instrument runner: re-runs v1.5 strategy + extracts the rich trade ledger.
# ---------------------------------------------------------------------------
def run_one_instrument_postmortem(symbol: str, confidence: float = 0.65) -> pd.DataFrame:
    instruments_yaml = REPO / "config" / "instruments.yaml"
    calendars_yaml = REPO / "config" / "session_calendars.yaml"
    cfg = yaml.safe_load(instruments_yaml.read_text())
    cals = load_calendars(calendars_yaml)
    ic = cfg["instruments"][symbol]
    cal = cals[ic["calendar"]]
    source_df = load_instrument_csv(REPO / ic["file"], cal)

    ensemble_csv = REPO / "features" / f"projection_ensemble__{symbol}.csv"
    regime_csv = REPO / "features" / f"regime__{symbol}.csv"
    absorption_csv = REPO / "features" / f"absorption__{symbol}.csv"
    vacuum_csv = REPO / "features" / f"vacuum__{symbol}.csv"
    tpo_csv = REPO / "features" / f"tpo__{symbol}.csv"

    sig = recompute_trade_eligibility(
        ensemble_csv=ensemble_csv, source_df=source_df, regime_csv=regime_csv,
        absorption_csv=absorption_csv, vacuum_csv=vacuum_csv, tpo_csv=tpo_csv,
        params=EligibilityParams(latest_entry_time_et=ic["latest_entry_time"],
                                   min_confidence=confidence),
        structural_stop_params=StructuralStopParams(structural_buffer_atr_mult=PRIMARY_BUFFER,
                                                      fallback_buffer_atr_mult=PRIMARY_BUFFER),
    )

    roll_skip_idxs, _ = build_roll_skip_idxs(
        source_df=source_df,
        roll_candidates_csv=REPO / "reports" / "v1_4_roll_candidates.csv",
        symbol=symbol, mode="v1_4",
    )

    p = BacktestParams(
        starting_equity=100_000.0, risk_per_trade=0.005,
        slippage_mult=1.0, slippage_ticks=1.0,
        use_projection_exits=True,
        tp1_partial_fraction=0.5,
        fallback_buffer_atr_mult=PRIMARY_BUFFER,
        projection_hold_mult=PRIMARY_HOLD_MULT,
        projection_hold_fallback=12,
    )
    engine = EventEngine(p)
    inst_cfg = dict(symbol=symbol, family=ic["family"],
                    point_value=float(ic["point_value"]),
                    tick_size=float(ic["tick_size"]),
                    tick_value=float(ic["tick_value"]))
    res = engine.run(
        source_df=source_df, signals_df=sig, inst_cfg=inst_cfg,
        cost_fn=fixed_tick_cost, cost_model_name="fixed_tick",
        roll_skip_idxs=roll_skip_idxs,
    )

    # Per-trade context vectors.
    highs = source_df["high"].values
    lows = source_df["low"].values
    closes = source_df["close"].values
    sds = source_df["session_date"].values
    atrs = source_df["atr_20"].values
    point_value = float(ic["point_value"])

    proj_close_low = sig["projected_close_low"].values
    proj_close_mid = sig["projected_close_mid"].values
    proj_close_high = sig["projected_close_high"].values
    proj_completion_median = sig["projected_completion_median"].values
    regime_label = sig["regime_label"].values
    vpin_gate = sig["vpin_gate"].values
    reason_codes = sig["reason_codes"].values if "reason_codes" in sig.columns else \
                   np.array([""] * len(sig))
    has_struct = sig["has_structural_stop"].values
    session_phase = sig["session_phase"].values

    rows = []
    for t in res.trades:
        ei = t.entry_idx
        si = ei - 1                # signal bar (one before the entry bar)
        if si < 0 or si >= len(sig):
            continue
        atr_e = float(atrs[ei]) if ei < len(atrs) else float("nan")
        proj_med = float(proj_completion_median[si]) if si < len(proj_completion_median) else np.nan
        original_max_hold = max(1, ceil((proj_med if proj_med == proj_med and proj_med >= 1 else 8)
                                          * PRIMARY_HOLD_MULT))
        # Recover the original anchor: stop_price = anchor - direction × 0.5 × ATR.
        # Thus anchor = stop_price + direction × 0.5 × ATR.  Works for both
        # structural (anchor = absorption/vacuum/tpo level) and fallback
        # (anchor = synthetic_open).
        anchor = float(t.stop_price) + t.direction * PRIMARY_BUFFER * atr_e

        # Counterfactual stops (W1 = buf 1.0 same hold; W2 = buf 2.0 + 2× hold).
        stop_w1 = anchor - t.direction * 1.0 * atr_e
        stop_w2 = anchor - t.direction * 2.0 * atr_e
        max_hold_w2 = max(1, ceil((proj_med if proj_med == proj_med and proj_med >= 1 else 8) * 3.0))

        # Replay counterfactuals.
        cf_w1 = replay_trade(
            entry_idx=ei, direction=t.direction,
            stop_price=stop_w1, target_price=float(t.target_price),
            max_bars_hold=original_max_hold,
            highs=highs, lows=lows, closes=closes, session_dates=sds,
        )
        cf_w2 = replay_trade(
            entry_idx=ei, direction=t.direction,
            stop_price=stop_w2, target_price=float(t.target_price),
            max_bars_hold=max_hold_w2,
            highs=highs, lows=lows, closes=closes, session_dates=sds,
        )

        # Projection durability over 3× original_max_hold bars.
        dur = projection_durability(
            entry_idx=ei, direction=t.direction,
            target_price=float(t.target_price),
            proj_close_low=float(proj_close_low[si]),
            proj_close_high=float(proj_close_high[si]),
            durability_window=3 * original_max_hold,
            highs=highs, lows=lows, session_dates=sds,
        )

        # Counterfactual PnL — use ORIGINAL contracts to isolate exit effect.
        cf_w1_pnl = (cf_w1["exit_price"] - t.entry_price) * t.direction * point_value * t.contracts
        cf_w2_pnl = (cf_w2["exit_price"] - t.entry_price) * t.direction * point_value * t.contracts

        rows.append(dict(
            symbol=symbol,
            entry_idx=int(ei),
            entry_time=str(t.entry_time),
            session_date=str(sds[ei]),
            direction=int(t.direction),
            contracts=int(t.contracts),
            entry_price=float(t.entry_price),
            atr_at_entry=atr_e,
            anchor=anchor,
            has_structural_override=bool(has_struct[si]),
            # original
            stop_price=float(t.stop_price),
            target_price=float(t.target_price),
            tp1_price=float(t.tp1_price) if t.tp1_price is not None else float("nan"),
            original_max_bars_hold=int(original_max_hold),
            original_exit_idx=int(t.exit_idx) if t.exit_idx is not None else -1,
            original_exit_reason=str(t.exit_reason),
            original_net_pnl=float(t.net_pnl),
            # counterfactual W1
            stop_w1=float(stop_w1),
            cf_w1_exit_idx=int(cf_w1["exit_idx"]),
            cf_w1_exit_reason=cf_w1["exit_reason"],
            cf_w1_exit_price=float(cf_w1["exit_price"]),
            cf_w1_pnl_gross=float(cf_w1_pnl),
            # counterfactual W2
            stop_w2=float(stop_w2),
            cf_w2_exit_idx=int(cf_w2["exit_idx"]),
            cf_w2_exit_reason=cf_w2["exit_reason"],
            cf_w2_exit_price=float(cf_w2["exit_price"]),
            cf_w2_pnl_gross=float(cf_w2_pnl),
            cf_w2_max_bars_hold=int(max_hold_w2),
            # projection durability
            proj_close_low=float(proj_close_low[si]),
            proj_close_mid=float(proj_close_mid[si]),
            proj_close_high=float(proj_close_high[si]),
            proj_completion_median=float(proj_med),
            durability_window=int(3 * original_max_hold),
            durability_visited_zone=bool(dur["visited_zone"]),
            durability_reached_tp2=bool(dur["reached_tp2"]),
            durability_tp2_first_idx=int(dur["tp2_first_idx"]) if dur["tp2_first_idx"] is not None else -1,
            # entry context
            regime_label=str(regime_label[si]),
            vpin_gate=str(vpin_gate[si]),
            reason_codes=str(reason_codes[si]),
            session_phase=str(session_phase[si]),
            entry_hour_et=int(pd.Timestamp(t.entry_time).hour),
            entry_minute_et=int(pd.Timestamp(t.entry_time).minute),
            family=t.family,
        ))

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Aggregation + reporting.
# ---------------------------------------------------------------------------
def aggregate_stopped_outcomes(df: pd.DataFrame) -> dict:
    """Decision-tree-ready aggregates on stopped trades."""
    stopped = df[df["original_exit_reason"].str.contains("^stop$|^stop_after_tp1$", regex=True)]
    n_stopped = len(stopped)
    if n_stopped == 0:
        return dict(n_stopped=0)
    # W1 counterfactual: of the stopped trades, fraction that NOW hit TP2.
    w1_tp2 = (stopped["cf_w1_exit_reason"] == "tp2").sum()
    w1_stop = (stopped["cf_w1_exit_reason"] == "stop").sum()
    w1_time = (stopped["cf_w1_exit_reason"] == "time_stop").sum()
    w1_se = (stopped["cf_w1_exit_reason"] == "session_end").sum()
    w2_tp2 = (stopped["cf_w2_exit_reason"] == "tp2").sum()
    w2_stop = (stopped["cf_w2_exit_reason"] == "stop").sum()
    w2_time = (stopped["cf_w2_exit_reason"] == "time_stop").sum()
    w2_se = (stopped["cf_w2_exit_reason"] == "session_end").sum()
    dur_verified = stopped["durability_reached_tp2"].sum()
    dur_visited_zone = stopped["durability_visited_zone"].sum()
    return dict(
        n_stopped=int(n_stopped),
        w1_tp2_rate=float(w1_tp2 / n_stopped),
        w1_stop_rate=float(w1_stop / n_stopped),
        w1_time_rate=float(w1_time / n_stopped),
        w1_se_rate=float(w1_se / n_stopped),
        w2_tp2_rate=float(w2_tp2 / n_stopped),
        w2_stop_rate=float(w2_stop / n_stopped),
        w2_time_rate=float(w2_time / n_stopped),
        w2_se_rate=float(w2_se / n_stopped),
        durability_verified_rate=float(dur_verified / n_stopped),
        durability_visited_zone_rate=float(dur_visited_zone / n_stopped),
    )


def hypothetical_pf(df: pd.DataFrame, *, scenario: str) -> dict:
    """Compute hypothetical PF using ORIGINAL outcomes for non-stopped trades and
    COUNTERFACTUAL outcomes for stopped trades. This is the cleanest forensic
    estimate -- only stopped trades change.
    """
    pnl_col = {"original": "original_net_pnl",
               "w1": "cf_w1_pnl_gross",
               "w2": "cf_w2_pnl_gross"}[scenario]
    stopped_mask = df["original_exit_reason"].str.contains("^stop$|^stop_after_tp1$", regex=True)
    # For non-stopped trades, use original net P&L.
    non_stopped_pnl = df.loc[~stopped_mask, "original_net_pnl"].sum()
    if scenario == "original":
        all_pnl = df["original_net_pnl"]
    else:
        # Use counterfactual PnL only for stopped trades; non-stopped keep original.
        cf = df["original_net_pnl"].copy()
        cf.loc[stopped_mask] = df.loc[stopped_mask, pnl_col]
        all_pnl = cf
    wins = all_pnl[all_pnl > 0].sum()
    losses = all_pnl[all_pnl < 0].sum()
    pf = float(wins / abs(losses)) if losses != 0 else float("inf")
    return dict(n_trades=int(len(all_pnl)),
                net_pnl=float(all_pnl.sum()),
                pf=pf,
                win_rate=float((all_pnl > 0).mean()))


def winners_profile(df: pd.DataFrame) -> pd.DataFrame:
    """For TP2 winners (exit_reason ∈ {'tp2','tp2_after_tp1'}), characterise
    distinguishing entry features vs the full population.
    """
    is_winner = df["original_exit_reason"].isin(["tp2", "tp2_after_tp1"])
    out_rows = []
    cats = ["regime_label", "vpin_gate", "session_phase", "has_structural_override"]
    for c in cats:
        for v, sub in df.groupby(c):
            n = len(sub)
            n_w = is_winner.loc[sub.index].sum()
            out_rows.append(dict(
                feature=c, value=str(v),
                n_trades=int(n),
                n_winners=int(n_w),
                winner_rate=float(n_w / max(n, 1)),
            ))
    # Override-kind profile
    overrides = df["reason_codes"].astype(str)
    df = df.copy()
    df["override_kind"] = np.where(overrides.str.contains("absorption"), "absorption",
                            np.where(overrides.str.contains("failed_auction"), "failed_auction",
                              np.where(overrides.str.contains("vacuum_continuation"), "vacuum_continuation",
                                np.where(overrides.str.contains("vacuum_reversal"), "vacuum_reversal", "none"))))
    for v, sub in df.groupby("override_kind"):
        n_w = is_winner.loc[sub.index].sum()
        out_rows.append(dict(
            feature="override_kind", value=v,
            n_trades=int(len(sub)),
            n_winners=int(n_w),
            winner_rate=float(n_w / max(len(sub), 1)),
        ))
    # Time-of-day (entry hour ET)
    for v, sub in df.groupby("entry_hour_et"):
        n_w = is_winner.loc[sub.index].sum()
        out_rows.append(dict(
            feature="entry_hour_et", value=str(v),
            n_trades=int(len(sub)),
            n_winners=int(n_w),
            winner_rate=float(n_w / max(len(sub), 1)),
        ))
    return pd.DataFrame(out_rows)


def grid_width_to_atr_ratio(symbol: str, atr_median: float) -> float:
    """Approximate the family round-number grid / ATR ratio (BLOCKERS §16)."""
    GRID = {
        "ES": 5.0, "MES": 5.0,            # 5 pts on S&P
        "MNQ": 25.0,                       # 25 pts on Nasdaq (BLOCKERS §16: 25 confirmed)
        "YM": 100.0, "MYM": 100.0,        # 100 pts on Dow
        "RTY": 5.0, "M2K": 5.0,           # 5 pts on Russell
        "MGC": 10.0,                       # $10 on gold
        "MCL": 1.0,                        # $1 on crude
    }
    g = GRID.get(symbol, np.nan)
    return float(g / atr_median) if atr_median > 0 else float("nan")


# ---------------------------------------------------------------------------
# Decision-tree verdict (per owner spec).
# ---------------------------------------------------------------------------
def decide_verdict(*, w1_fix_rate: float, w2_fix_rate: float,
                    durability_rate: float) -> tuple[str, str]:
    """
    OWNER decision tree (verbatim from prompt):
      - wider-stop-only fixes >=40% AND eventual-verification >=50% -> Phase 6 justified.
      - wider-stop-only fixes <20% -> wider stops won't save the strategy.
      - wider-stop+longer-hold fixes 40-60% AND eventual-verification 50-70%
                                                          -> tunable but marginal.
      - projection verification < 30% even at 3× horizon -> Option A.
    """
    notes = []
    if durability_rate < 0.30:
        return ("A_STOP",
                f"Projection eventual-verification rate is {durability_rate*100:.1f}% < 30% "
                f"at 3× horizon. The Phase 4 §11.2 close-zone gate is NOT predictive at "
                f"trade-management timescales. Wider stops cannot save what the projection "
                f"never delivers. Owner-defined trigger for OPTION A (accept and stop).")
    if w1_fix_rate >= 0.40 and durability_rate >= 0.50:
        return ("B_PHASE6_JUSTIFIED",
                f"Wider stop alone fixes {w1_fix_rate*100:.1f}% of stopped trades "
                f"(≥40%) AND projection verifies {durability_rate*100:.1f}% (≥50%). "
                f"Owner-defined trigger for PHASE 6 walk-forward search on "
                f"structural_buffer_atr_mult, projection_hold_mult, tp1_partial_fraction.")
    if w1_fix_rate < 0.20:
        return ("A_STOP",
                f"Wider stop alone fixes only {w1_fix_rate*100:.1f}% of stopped trades "
                f"(<20%). Wider stops won't save the strategy. Owner-defined trigger for "
                f"OPTION A (accept and stop).")
    if 0.40 <= w2_fix_rate <= 0.60 and 0.50 <= durability_rate <= 0.70:
        return ("B_PHASE6_MARGINAL",
                f"Wider stop + longer hold fixes {w2_fix_rate*100:.1f}% of stopped trades "
                f"(in 40-60% band) and projection verifies {durability_rate*100:.1f}% "
                f"(in 50-70% band). Strategy is TUNABLE BUT MARGINAL — Phase 6 may yield "
                f"a profitable variant but optimization gains will be small.")
    return ("INDETERMINATE",
            f"Outcome lies outside the owner's decision-tree thresholds: "
            f"W1 fix rate={w1_fix_rate*100:.1f}%, W2 fix rate={w2_fix_rate*100:.1f}%, "
            f"durability={durability_rate*100:.1f}%. Surface to owner for "
            f"clarification before proceeding to either Phase 6 or Option A.")


def write_postmortem_md(*,
    instrument_aggs: dict,
    portfolio_agg: dict,
    portfolio_pf: dict,
    winners: pd.DataFrame,
    family_grid: pd.DataFrame,
    verdict: tuple[str, str],
    confidence: float,
    out_path: Path,
) -> None:
    lines: list[str] = []
    lines.append(f"# Phase 5.5 Option C — Forensic Post-Mortem (conf={confidence})\n")
    lines.append(
        "_Forensic analysis on the existing v1.5 trade ledger. No new backtest, "
        "no parameter tuning, no optimization. Counterfactuals:_\n"
        "- **W1**: structural_buffer_atr_mult = 1.0 (vs original 0.5), same hold.\n"
        "- **W2**: structural_buffer_atr_mult = 2.0 AND projection_hold_mult = 3.0 (vs 1.5).\n"
        "- **Durability**: did price reach TP2 within 3× original max_bars_hold?\n"
    )

    # Portfolio-level headline
    lines.append("## Portfolio (all 9 instruments) — gating numbers\n")
    a = portfolio_agg
    lines.append(f"- Stopped trades in the original v1.5 ledger: **{a['n_stopped']:,}**.")
    lines.append(f"- **W1 fixes (wider stop only → TP2): {a['w1_tp2_rate']*100:.1f}%**")
    lines.append(f"- W1 still-stops: {a['w1_stop_rate']*100:.1f}%  ;  W1 still-time-stops: {a['w1_time_rate']*100:.1f}%  ;  W1 session-end: {a['w1_se_rate']*100:.1f}%")
    lines.append(f"- **W2 fixes (wider + longer → TP2): {a['w2_tp2_rate']*100:.1f}%**")
    lines.append(f"- W2 still-stops: {a['w2_stop_rate']*100:.1f}%  ;  W2 still-time-stops: {a['w2_time_rate']*100:.1f}%  ;  W2 session-end: {a['w2_se_rate']*100:.1f}%")
    lines.append(f"- **Projection durability (TP2 reached within 3× horizon): {a['durability_verified_rate']*100:.1f}%**")
    lines.append(f"- Zone-visit durability (projected close zone ever touched): {a['durability_visited_zone_rate']*100:.1f}%")

    # Hypothetical PF
    lines.append("\n## Hypothetical Portfolio P&L (counterfactual exits, original contracts)\n")
    lines.append(
        "_The non-stopped trades keep their original outcome; stopped trades adopt "
        "the counterfactual exit. Uses GROSS P&L for the new exits (no slip/cost) for "
        "speed — original costs already netted out._\n"
    )
    lines.append("| Scenario | Trades | Net P&L | PF | Win rate |")
    lines.append("|---|---|---|---|---|")
    for k in ("original", "w1", "w2"):
        m = portfolio_pf[k]
        lines.append(f"| {k} | {m['n_trades']:,} | "
                     f"{m['net_pnl']:,.0f} | {m['pf']:.2f} | {m['win_rate']*100:.1f}% |")

    # Decision-tree verdict
    lines.append("\n## Decision-tree verdict\n")
    lines.append(f"**{verdict[0]}** — {verdict[1]}\n")

    # Per-instrument table
    lines.append("\n## Per-instrument — fix rates and durability\n")
    lines.append("| Symbol | n_stopped | W1 → TP2 | W2 → TP2 | Durability (TP2 in 3×) | Zone visit |")
    lines.append("|---|---|---|---|---|---|")
    for sym, ag in instrument_aggs.items():
        if ag.get("n_stopped", 0) == 0:
            lines.append(f"| {sym} | 0 | — | — | — | — |")
            continue
        lines.append(
            f"| {sym} | {ag['n_stopped']:,} | "
            f"{ag['w1_tp2_rate']*100:.1f}% | "
            f"{ag['w2_tp2_rate']*100:.1f}% | "
            f"{ag['durability_verified_rate']*100:.1f}% | "
            f"{ag['durability_visited_zone_rate']*100:.1f}% |"
        )

    # YM/MNQ family-grid profile
    lines.append("\n## Family grid-width / ATR ratio (BLOCKERS §16 hypothesis)\n")
    lines.append("| Symbol | family | grid (pts) | median ATR | grid/ATR | TP2 win rate |")
    lines.append("|---|---|---|---|---|---|")
    for _, r in family_grid.iterrows():
        lines.append(f"| {r['symbol']} | {r['family']} | {r['grid_points']:.1f} | "
                     f"{r['median_atr']:.2f} | {r['grid_to_atr']:.2f} | "
                     f"{r['tp2_winrate']*100:.1f}% |")

    # Winners profile
    lines.append("\n## TP2 winners — feature profile vs full population\n")
    lines.append("| Feature | Value | n_trades | n_winners | Winner rate |")
    lines.append("|---|---|---|---|---|")
    for _, r in winners.sort_values(["feature", "winner_rate"], ascending=[True, False]).iterrows():
        if r["n_trades"] < 20:    # noise floor
            continue
        lines.append(f"| {r['feature']} | {r['value']} | {int(r['n_trades']):,} | "
                     f"{int(r['n_winners']):,} | {r['winner_rate']*100:.1f}% |")

    # Interpretation
    lines.append("\n## Interpretation\n")
    lines.append("- The gating question is: **does the projected close zone get visited / TP2 reached when given more time?**")
    lines.append(f"  - Portfolio durability rate: **{a['durability_verified_rate']*100:.1f}%** (TP2 reached in 3× horizon).")
    lines.append(f"  - Portfolio zone-visit rate: **{a['durability_visited_zone_rate']*100:.1f}%** (price touched the projected close envelope at any point in 3× horizon).")
    lines.append(
        "- If durability is high and W1 fixes most stops, **the projection IS durable and "
        "wider stops would convert losers into winners.** Phase 6 is justified.")
    lines.append(
        "- If durability is low, the projection only verifies on the 6% TP2-winning trades — "
        "the §11.2 close-zone gate is misleading at trade-management timescales. No amount of "
        "Phase 6 tuning will save the strategy because the underlying projection is not "
        "actionable. Option A is the honest answer.")

    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confidence", type=float, default=0.65,
                     help="primary confidence threshold to analyze")
    ap.add_argument("--symbols", nargs="*", default=None,
                     help="restrict to a subset of symbols (default all 9)")
    args = ap.parse_args()

    reports_dir = REPO / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((REPO / "config" / "instruments.yaml").read_text())
    syms = args.symbols if args.symbols else list(cfg["instruments"].keys())

    all_trades: list[pd.DataFrame] = []
    for sym in syms:
        logger.info(f"=== post-mortem: {sym} ===")
        try:
            df_sym = run_one_instrument_postmortem(symbol=sym, confidence=args.confidence)
        except Exception as e:
            logger.exception(f"{sym} failed: {e}")
            continue
        all_trades.append(df_sym)
        logger.info(f"  {sym}: {len(df_sym):,} trades captured")

    if not all_trades:
        logger.error("no trades captured")
        return 2
    df_all = pd.concat(all_trades, ignore_index=True)
    df_all.to_csv(reports_dir / "v1_5_phase5_postmortem_trades.csv", index=False)
    logger.info(f"wrote per-trade ledger: {len(df_all):,} rows")

    # Per-instrument aggregates.
    inst_aggs = {}
    for sym, sub in df_all.groupby("symbol"):
        inst_aggs[sym] = aggregate_stopped_outcomes(sub)
    port_agg = aggregate_stopped_outcomes(df_all)

    # Hypothetical PF per scenario.
    port_pf = {k: hypothetical_pf(df_all, scenario=k)
               for k in ("original", "w1", "w2")}

    # Winners profile and YM/MNQ grid table.
    winners = winners_profile(df_all)
    winners.to_csv(reports_dir / "v1_5_phase5_postmortem_winners.csv", index=False)

    family_rows = []
    for sym, sub in df_all.groupby("symbol"):
        med_atr = float(sub["atr_at_entry"].median())
        is_win = sub["original_exit_reason"].isin(["tp2", "tp2_after_tp1"])
        family_rows.append(dict(
            symbol=sym,
            family=sub["family"].iloc[0] if not sub.empty else "",
            grid_points={"ES": 5.0, "MES": 5.0, "MNQ": 25.0, "YM": 100.0, "MYM": 100.0,
                          "RTY": 5.0, "M2K": 5.0, "MGC": 10.0, "MCL": 1.0}.get(sym, float("nan")),
            median_atr=med_atr,
            grid_to_atr=grid_width_to_atr_ratio(sym, med_atr),
            tp2_winrate=float(is_win.mean()),
        ))
    family_grid = pd.DataFrame(family_rows)

    # Decision verdict.
    verdict = decide_verdict(
        w1_fix_rate=port_agg.get("w1_tp2_rate", 0.0),
        w2_fix_rate=port_agg.get("w2_tp2_rate", 0.0),
        durability_rate=port_agg.get("durability_verified_rate", 0.0),
    )
    logger.info(f"verdict: {verdict[0]} — {verdict[1]}")

    write_postmortem_md(
        instrument_aggs=inst_aggs,
        portfolio_agg=port_agg,
        portfolio_pf=port_pf,
        winners=winners,
        family_grid=family_grid,
        verdict=verdict,
        confidence=args.confidence,
        out_path=reports_dir / "v1_5_phase5_postmortem.md",
    )
    logger.info(f"wrote {reports_dir / 'v1_5_phase5_postmortem.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
