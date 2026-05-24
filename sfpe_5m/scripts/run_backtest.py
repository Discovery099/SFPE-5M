"""Phase 5 — Master backtest driver.

Runs all 9 instruments × 10 strategy variants + 10 baselines, with strict ordering:
  1. Trade-count audit FIRST. If portfolio total < 200 OR per-instrument < 50 on
     active instruments, STOP and report before computing PF/Sharpe.
  2. After audit passes, compute full metrics per (variant × instrument) +
     portfolio aggregation with family concurrency.
  3. Write all Phase 5 deliverables (summary MD, equity curves PNG, baseline
     table, slippage sensitivity, stress-window columns, roll-skip log).

Outputs to `reports/`:
  v1_4_trade_count_audit.md                # MANDATORY first deliverable
  v1_4_phase5_summary.md                   # full performance (gate after audit)
  v1_4_phase5_metrics.csv                  # per-variant per-instrument metrics
  v1_4_phase5_baselines.csv                # 10-baseline comparison table
  v1_4_phase5_slippage_table.csv           # slippage sensitivity per instr
  v1_4_phase5_stress_windows.csv           # stress-window column breakdown
  v1_4_phase5_roll_skip_blocked.csv        # user-requested: roll-skip blocked counts
  v1_4_phase5_per_instrument_equity__<SYM>.csv
  v1_4_phase5_per_instrument_equity__<SYM>__conf=0.65.png
  v1_4_phase5_portfolio_equity__conf=0.50.csv / png
  v1_4_phase5_portfolio_equity__conf=0.65.csv / png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from loguru import logger

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.backtest import (
    compute_metrics, regime_breakdown,
    enforce_family_concurrency, portfolio_equity_curve, FAMILY_OF_SYMBOL,
    BacktestParams, trades_to_dataframe,
    BASELINES,
)
from sfpe.backtest.runner import (
    run_one_instrument, default_variants,
)


STRESS_WINDOWS = [
    ("covid",     pd.Timestamp("2020-02-20").date(), pd.Timestamp("2020-05-31").date()),
    ("rates",     pd.Timestamp("2022-06-01").date(), pd.Timestamp("2022-10-31").date()),
    ("banks",     pd.Timestamp("2023-03-01").date(), pd.Timestamp("2023-09-30").date()),
]


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _trade_in_stress(t_row: pd.Series, label: str) -> bool:
    """Whether a trade falls inside a named stress window."""
    try:
        sd = pd.Timestamp(t_row["session_date"]).date()
    except Exception:
        return False
    for lbl, lo, hi in STRESS_WINDOWS:
        if lbl == label and lo <= sd <= hi:
            return True
    return False


def trade_count_audit(inst_results: list[dict]) -> dict:
    """First deliverable. Counts at conf 0.50 and 0.65, primary cost model 1x slippage."""
    rows = []
    for ir in inst_results:
        sym = ir["symbol"]
        for thr in (0.50, 0.65):
            vname = f"strategy__cost=fixed_tick__slip=1x__conf={thr:.2f}"
            res = ir["strategy_results"].get(vname)
            n_trades = len(res.trades) if res else 0
            n_eligible = ir["n_eligible_at_thresholds"].get(thr, 0)
            n_blocked_by_rollskip = ir["roll_skip_blocked_signal_count"].get(thr, 0)
            rows.append(dict(
                symbol=sym, confidence=thr,
                n_eligible_bars=n_eligible,
                n_roll_skip_blocked_eligible=n_blocked_by_rollskip,
                n_trades=n_trades,
                conversion_rate=(n_trades / max(n_eligible, 1)),
            ))
    return rows


def write_trade_count_audit_md(audit_rows: list[dict], out_path: Path) -> dict:
    """Trade-count audit MD. Returns dict {gate_pass: bool, per_threshold_totals: ...}.
    Gate definition (user-locked):
      - Portfolio total trades >= 200 at primary threshold (conf=0.65), AND
      - Per active-instrument trades >= 50 (active = n_eligible_bars > 0).
    """
    df = pd.DataFrame(audit_rows)
    totals_by_thr = df.groupby("confidence")["n_trades"].sum().to_dict()
    # An instrument is "active" if it produced >0 eligible bars.
    df["active"] = df["n_eligible_bars"] > 0
    failing_inst_by_thr: dict[float, list[str]] = {}
    for thr in (0.50, 0.65):
        sub = df[(df["confidence"] == thr) & (df["active"])]
        bad = sub[sub["n_trades"] < 50]
        failing_inst_by_thr[thr] = bad["symbol"].tolist()

    gate_pass_065 = (
        totals_by_thr.get(0.65, 0) >= 200
        and len(failing_inst_by_thr[0.65]) == 0
    )

    lines: list[str] = []
    lines.append("# Phase 5 Step — Trade Count Audit (PRE-PF / PRE-SHARPE)\n")
    lines.append(
        "_Per user lock: PF / Sharpe are not statistically meaningful on <200 portfolio "
        "trades or <50 per-active-instrument trades._\n"
    )
    lines.append("\n## Per-instrument per-threshold breakdown\n")
    lines.append(
        "| Symbol | Conf | Eligible bars | Blocked-by-roll-skip | Trades | "
        "Conversion (trades/eligible) | Per-instr ≥50? |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for r in audit_rows:
        is_active = r["n_eligible_bars"] > 0
        ok = (not is_active) or (r["n_trades"] >= 50)
        lines.append(
            f"| {r['symbol']} | {r['confidence']:.2f} | {r['n_eligible_bars']:,} | "
            f"{r['n_roll_skip_blocked_eligible']:,} | {r['n_trades']:,} | "
            f"{r['conversion_rate']*100:.1f}% | "
            f"{'✅' if ok else '❌ <50'} |"
        )
    lines.append("\n## Portfolio totals by confidence threshold\n")
    lines.append("| Confidence | Portfolio total trades | ≥ 200? |")
    lines.append("|---|---|---|")
    for thr in (0.50, 0.65):
        n = int(totals_by_thr.get(thr, 0))
        lines.append(f"| {thr:.2f} | {n:,} | {'✅' if n >= 200 else '❌ <200'} |")

    lines.append("\n## Gate verdict (primary threshold conf=0.65)\n")
    if gate_pass_065:
        lines.append(
            "✅ **PASS** — portfolio ≥ 200 trades AND every active instrument ≥ 50 trades. "
            "Proceeding to full PF / Sharpe / DSR computation.\n"
        )
    else:
        reasons = []
        if totals_by_thr.get(0.65, 0) < 200:
            reasons.append(f"portfolio trades = {int(totals_by_thr.get(0.65, 0))} < 200")
        if failing_inst_by_thr[0.65]:
            reasons.append(
                f"per-instrument <50 on: {', '.join(failing_inst_by_thr[0.65])}"
            )
        lines.append(
            "⚠️ **PAUSE** — " + " ; ".join(reasons) + ". "
            "Surfacing to user before computing P&L statistics (PF on a tiny sample "
            "is misleading).\n"
        )
    # Note: roll-skip blocked count for the user (Phase 5.2 lock)
    lines.append("\n## User-requested: trades blocked by roll-skip rule\n")
    for r in audit_rows:
        if r["n_eligible_bars"] > 0:
            pct = 100.0 * r["n_roll_skip_blocked_eligible"] / r["n_eligible_bars"]
            flag = "⚠️ >5%" if pct > 5.0 else "✅"
            lines.append(
                f"- {r['symbol']} (conf={r['confidence']:.2f}): "
                f"{r['n_roll_skip_blocked_eligible']:,} of {r['n_eligible_bars']:,} "
                f"eligible-bar signals blocked ({pct:.2f}%) {flag}"
            )

    out_path.write_text("\n".join(lines))
    return dict(gate_pass=gate_pass_065,
                totals_by_thr=totals_by_thr,
                failing_inst_by_thr=failing_inst_by_thr)


def per_instrument_metrics_table(inst_results: list[dict]) -> pd.DataFrame:
    """Wide CSV: one row per (symbol, variant_or_baseline)."""
    rows = []
    for ir in inst_results:
        sym = ir["symbol"]
        for vname, res in ir["strategy_results"].items():
            df = trades_to_dataframe(res.trades)
            m = compute_metrics(df, starting_equity=res.params.starting_equity)
            m["symbol"] = sym
            m["variant"] = vname
            m["kind"] = "strategy"
            rows.append(m)
        for bname, res in ir["baseline_results"].items():
            df = trades_to_dataframe(res.trades)
            m = compute_metrics(df, starting_equity=res.params.starting_equity)
            m["symbol"] = sym
            m["variant"] = f"baseline__{bname}"
            m["kind"] = "baseline"
            rows.append(m)
    return pd.DataFrame(rows)


def per_instrument_equity_csv(inst_results: list[dict], reports_dir: Path,
                                primary_variant: str) -> None:
    """Save per-instrument equity curves as CSV + PNG for the primary variant."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        plt = None
    for ir in inst_results:
        sym = ir["symbol"]
        res = ir["strategy_results"].get(primary_variant)
        if res is None or len(res.equity_curve) == 0:
            continue
        eq = res.equity_curve.reset_index()
        eq.columns = ["timestamp", "equity"]
        eq.to_csv(reports_dir / f"v1_4_phase5_per_instrument_equity__{sym}.csv",
                  index=False)
        if plt is not None:
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(eq["timestamp"], eq["equity"], lw=1.0)
            ax.set_title(f"{sym} — Strategy equity curve  ({primary_variant})")
            ax.set_xlabel("time")
            ax.set_ylabel("equity ($)")
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            fig.savefig(reports_dir / f"v1_4_phase5_per_instrument_equity__{sym}.png",
                        dpi=110)
            plt.close(fig)


def stress_window_breakdown(inst_results: list[dict],
                              primary_variant: str) -> pd.DataFrame:
    """Per-instrument net P&L within COVID / rates / banks windows, plus
    opening-30-min and closing-30-min slices."""
    out = []
    for ir in inst_results:
        sym = ir["symbol"]
        res = ir["strategy_results"].get(primary_variant)
        if res is None:
            continue
        df = trades_to_dataframe(res.trades)
        if df.empty:
            continue
        for lbl, lo, hi in STRESS_WINDOWS:
            mask = pd.to_datetime(df["session_date"]).dt.date.between(lo, hi)
            sub = df[mask]
            out.append(dict(
                symbol=sym, window=lbl,
                n_trades=len(sub),
                net_pnl=float(sub["net_pnl"].sum()) if not sub.empty else 0.0,
                win_rate=float((sub["net_pnl"] > 0).mean()) if not sub.empty else 0.0,
            ))
        # Open 30 min and Close 30 min.
        et = pd.to_datetime(df["entry_time"])
        op_mask = (et.dt.hour * 60 + et.dt.minute) < (9 * 60 + 60 + 30)  # 09:30..10:00 ET (loader is tz-aware)
        cl_mask = (et.dt.hour * 60 + et.dt.minute) >= (15 * 60 + 30)
        for lbl, m in (("open_30min", op_mask), ("close_30min", cl_mask)):
            sub = df[m]
            out.append(dict(
                symbol=sym, window=lbl,
                n_trades=len(sub),
                net_pnl=float(sub["net_pnl"].sum()) if not sub.empty else 0.0,
                win_rate=float((sub["net_pnl"] > 0).mean()) if not sub.empty else 0.0,
            ))
    return pd.DataFrame(out)


def portfolio_aggregate(inst_results: list[dict], variant_name: str,
                          reports_dir: Path, conf_label: str) -> dict:
    """Apply family concurrency across all 9 instruments for a single variant.

    Saves portfolio equity curve CSV + PNG with conf_label suffix.
    Returns metrics dict.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        plt = None
    trades_by_symbol = {}
    for ir in inst_results:
        sym = ir["symbol"]
        res = ir["strategy_results"].get(variant_name)
        if res is None:
            continue
        trades_by_symbol[sym] = res.trades
    port = enforce_family_concurrency(trades_by_symbol)
    eq = portfolio_equity_curve(port.accepted_trades)
    eq_df = eq.reset_index()
    eq_df.columns = ["timestamp", "equity"]
    eq_df.to_csv(reports_dir / f"v1_4_phase5_portfolio_equity__{conf_label}.csv",
                 index=False)
    if plt is not None and len(eq) > 1:
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(eq.index, eq.values, lw=1.0)
        ax.set_title(f"Portfolio equity curve  ({variant_name})")
        ax.set_xlabel("time")
        ax.set_ylabel("equity ($)")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(reports_dir / f"v1_4_phase5_portfolio_equity__{conf_label}.png",
                    dpi=110)
        plt.close(fig)
    # Metrics on portfolio-accepted trades.
    df = port.accepted_df
    m = compute_metrics(df) if not df.empty else dict(n_trades=0)
    m["accepted_by_symbol"] = port.accepted_by_symbol
    m["blocked_by_symbol"] = port.blocked_by_symbol
    m["blocked_by_family"] = port.blocked_by_family
    return m


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None,
                     help="restrict to a subset of symbols (default all 9)")
    ap.add_argument("--skip-baselines", action="store_true")
    ap.add_argument("--skip-strategy", action="store_true")
    args = ap.parse_args()

    reports_dir = REPO / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((REPO / "config" / "instruments.yaml").read_text())
    syms = args.symbols if args.symbols else list(cfg["instruments"].keys())

    inst_results: list[dict] = []
    for sym in syms:
        logger.info(f"=== Phase-5 backtest run: {sym} ===")
        try:
            ir = run_one_instrument(
                symbol=sym, repo=REPO,
                run_strategy=not args.skip_strategy,
                run_baselines=not args.skip_baselines,
            )
        except Exception as e:
            logger.exception(f"{sym}: FAILED -> {e}")
            continue
        inst_results.append(ir)
        # Log roll-skip blocked counts immediately per user instruction.
        for thr in (0.50, 0.65):
            n_block = ir["roll_skip_blocked_signal_count"].get(thr, 0)
            n_elig = ir["n_eligible_at_thresholds"].get(thr, 0)
            pct = 100.0 * n_block / max(n_elig, 1)
            tag = "⚠️ >5%" if pct > 5.0 else "✅"
            logger.info(f"[{sym}] conf={thr:.2f}: roll-skip blocked "
                        f"{n_block}/{n_elig} eligible bars ({pct:.2f}%) {tag}")

    # STEP 1 — Trade count audit FIRST.
    audit_rows = trade_count_audit(inst_results)
    audit_md = reports_dir / "v1_4_trade_count_audit.md"
    gate = write_trade_count_audit_md(audit_rows, audit_md)
    pd.DataFrame(audit_rows).to_csv(
        reports_dir / "v1_4_phase5_trade_count_audit.csv", index=False)
    logger.info(f"wrote {audit_md} -- gate_pass={gate['gate_pass']}  "
                f"totals_by_thr={gate['totals_by_thr']}")

    # STEP 2 — Per-instrument metrics (always written for transparency).
    metrics_df = per_instrument_metrics_table(inst_results)
    metrics_df.to_csv(reports_dir / "v1_4_phase5_metrics.csv", index=False)
    logger.info(f"wrote {reports_dir/'v1_4_phase5_metrics.csv'}  rows={len(metrics_df):,}")

    # STEP 3 — Equity curves (primary variant: conf=0.65 fixed_tick 1×).
    primary_variant = "strategy__cost=fixed_tick__slip=1x__conf=0.65"
    per_instrument_equity_csv(inst_results, reports_dir, primary_variant)
    portfolio_065 = portfolio_aggregate(inst_results, primary_variant, reports_dir,
                                          conf_label="conf=0.65")
    portfolio_050 = portfolio_aggregate(inst_results,
                                          "strategy__cost=fixed_tick__slip=1x__conf=0.50",
                                          reports_dir, conf_label="conf=0.50")

    # STEP 4 — Stress windows.
    stress_df = stress_window_breakdown(inst_results, primary_variant)
    stress_df.to_csv(reports_dir / "v1_4_phase5_stress_windows.csv", index=False)

    # STEP 5 — Roll-skip blocked CSV.
    rs_rows = []
    for ir in inst_results:
        for thr in (0.50, 0.65):
            rs_rows.append(dict(
                symbol=ir["symbol"], confidence=thr,
                eligible_bars=ir["n_eligible_at_thresholds"].get(thr, 0),
                blocked_by_roll_skip=ir["roll_skip_blocked_signal_count"].get(thr, 0),
                roll_skip_bar_count=ir["roll_skip_bar_count"],
                flagged_roll_dates=ir["flagged_roll_date_count"],
            ))
    pd.DataFrame(rs_rows).to_csv(reports_dir / "v1_4_phase5_roll_skip_blocked.csv",
                                 index=False)

    # STEP 6 — Baselines comparison table.
    baseline_rows = []
    for ir in inst_results:
        sym = ir["symbol"]
        for bname, res in ir["baseline_results"].items():
            df = trades_to_dataframe(res.trades)
            m = compute_metrics(df)
            m["symbol"] = sym
            m["baseline"] = bname
            baseline_rows.append(m)
    pd.DataFrame(baseline_rows).to_csv(reports_dir / "v1_4_phase5_baselines.csv",
                                         index=False)

    # STEP 7 — Slippage sensitivity table.
    slip_rows = []
    for ir in inst_results:
        sym = ir["symbol"]
        for thr in (0.50, 0.65):
            for sm in (1.0, 2.0, 3.0):
                vname = f"strategy__cost=fixed_tick__slip={sm:.0f}x__conf={thr:.2f}"
                res = ir["strategy_results"].get(vname)
                if res is None:
                    continue
                df = trades_to_dataframe(res.trades)
                m = compute_metrics(df)
                slip_rows.append(dict(
                    symbol=sym, confidence=thr, slippage=sm,
                    n_trades=m.get("n_trades", 0),
                    net_profit=m.get("net_profit", 0.0),
                    profit_factor=m.get("profit_factor", float("nan")),
                    sharpe=m.get("sharpe", float("nan")),
                ))
    pd.DataFrame(slip_rows).to_csv(reports_dir / "v1_4_phase5_slippage_table.csv",
                                     index=False)

    # STEP 8 — Phase 5 summary MD.
    write_phase5_summary_md(
        inst_results=inst_results, metrics_df=metrics_df, gate=gate,
        portfolio_050=portfolio_050, portfolio_065=portfolio_065,
        stress_df=stress_df, slip_rows=slip_rows,
        baseline_rows=baseline_rows,
        reports_dir=reports_dir,
    )

    return 0 if gate["gate_pass"] else 2  # exit 2 if audit gate fails


def write_phase5_summary_md(*, inst_results, metrics_df, gate, portfolio_050,
                              portfolio_065, stress_df, slip_rows, baseline_rows,
                              reports_dir: Path) -> None:
    lines: list[str] = []
    lines.append("# SFPE-5M — Phase 5 Summary (v1.4)\n")
    lines.append(
        "_Strict ordering: trade-count audit FIRST → metrics → equity curves → "
        "stress windows → baseline comparison → slippage sensitivity._\n"
    )
    # Audit gate
    lines.append("## Audit gate\n")
    if gate["gate_pass"]:
        lines.append("✅ **PASS** — portfolio ≥ 200 trades at conf=0.65, "
                     "and every active instrument ≥ 50 trades.\n")
    else:
        lines.append("⚠️ **PAUSE** — trade-count audit fails one or more checks; "
                     "PF / Sharpe results below are reported for transparency but "
                     "must NOT be interpreted as a positive Phase-5 verdict. "
                     "See `v1_4_trade_count_audit.md` for details.\n")

    # Portfolio summary
    lines.append("## Portfolio (family-concurrency-enforced) — primary cost model 1× slippage\n")
    lines.append("| Conf | n_trades | net_profit | PF | Sharpe | Max DD | Win rate |")
    lines.append("|---|---|---|---|---|---|---|")
    for label, m in (("0.50", portfolio_050), ("0.65", portfolio_065)):
        lines.append(
            f"| {label} | {m.get('n_trades', 0):,} | "
            f"{m.get('net_profit', 0):,.0f} | "
            f"{m.get('profit_factor', float('nan')):.2f} | "
            f"{m.get('sharpe', float('nan')):.2f} | "
            f"{m.get('max_drawdown', 0):,.0f} | "
            f"{m.get('win_rate', 0)*100:.1f}% |"
        )

    # Per-instrument summary at conf=0.65 fixed_tick 1×
    lines.append("\n## Per-instrument summary (conf=0.65, fixed_tick, 1× slippage)\n")
    primary = "strategy__cost=fixed_tick__slip=1x__conf=0.65"
    sub = metrics_df[(metrics_df["variant"] == primary)]
    lines.append("| Symbol | n_trades | net_profit | PF | Sharpe | Max DD | Win rate |")
    lines.append("|---|---|---|---|---|---|---|")
    for _, r in sub.iterrows():
        lines.append(
            f"| {r['symbol']} | {r.get('n_trades', 0):,} | "
            f"{r.get('net_profit', 0):,.0f} | "
            f"{r.get('profit_factor', float('nan')):.2f} | "
            f"{r.get('sharpe', float('nan')):.2f} | "
            f"{r.get('max_drawdown', 0):,.0f} | "
            f"{r.get('win_rate', 0)*100:.1f}% |"
        )

    # Slippage sensitivity (averaged across instruments, primary cost)
    lines.append("\n## Slippage sensitivity (fixed_tick cost, per confidence threshold)\n")
    slip_df = pd.DataFrame(slip_rows)
    if not slip_df.empty:
        agg = (slip_df.groupby(["confidence", "slippage"])
                       .agg(total_trades=("n_trades", "sum"),
                            total_net_profit=("net_profit", "sum"),
                            mean_pf=("profit_factor", "mean"),
                            mean_sharpe=("sharpe", "mean"))
                       .reset_index().round(3))
        lines.append(
            "| conf | slip× | total_trades | total_net_profit | mean_PF | mean_Sharpe |"
        )
        lines.append("|---|---|---|---|---|---|")
        for _, r in agg.iterrows():
            lines.append(
                f"| {r['confidence']:.2f} | {r['slippage']:.0f}× | "
                f"{int(r['total_trades']):,} | "
                f"{r['total_net_profit']:,.0f} | "
                f"{r['mean_pf']:.2f} | "
                f"{r['mean_sharpe']:.2f} |"
            )

    # Stress window breakdown (primary variant)
    lines.append("\n## Stress windows (primary variant conf=0.65 1× fixed_tick)\n")
    if not stress_df.empty:
        agg = (stress_df.groupby("window")
                          .agg(total_trades=("n_trades", "sum"),
                                total_net=("net_pnl", "sum"),
                                mean_winrate=("win_rate", "mean"))
                          .reset_index().round(3))
        lines.append("| window | total_trades | total_net_pnl | mean_win_rate |")
        lines.append("|---|---|---|---|")
        for _, r in agg.iterrows():
            lines.append(
                f"| {r['window']} | {int(r['total_trades']):,} | "
                f"{r['total_net']:,.0f} | {r['mean_winrate']*100:.1f}% |"
            )

    # 10-baseline comparison table (per-instrument, then strategy delta)
    lines.append("\n## 10-baseline comparison (mean across active instruments)\n")
    bdf = pd.DataFrame(baseline_rows)
    if not bdf.empty:
        agg = (bdf.groupby("baseline")
                  .agg(mean_trades=("n_trades", "mean"),
                       mean_net=("net_profit", "mean"),
                       mean_pf=("profit_factor", "mean"),
                       mean_sharpe=("sharpe", "mean"),
                       mean_winrate=("win_rate", "mean"))
                  .reset_index().round(3))
        # Add the strategy as a row.
        strat = metrics_df[metrics_df["variant"] == primary].agg({
            "n_trades": "mean", "net_profit": "mean",
            "profit_factor": "mean", "sharpe": "mean", "win_rate": "mean"})
        agg = pd.concat([
            agg,
            pd.DataFrame([{
                "baseline": "STRATEGY (conf=0.65)",
                "mean_trades": strat["n_trades"], "mean_net": strat["net_profit"],
                "mean_pf": strat["profit_factor"], "mean_sharpe": strat["sharpe"],
                "mean_winrate": strat["win_rate"],
            }]).round(3),
        ], ignore_index=True)
        lines.append("| Variant | mean_trades | mean_net | mean_PF | mean_Sharpe | mean_winrate |")
        lines.append("|---|---|---|---|---|---|")
        for _, r in agg.iterrows():
            lines.append(
                f"| {r['baseline']} | {r['mean_trades']:.0f} | "
                f"{r['mean_net']:,.0f} | {r['mean_pf']:.2f} | "
                f"{r['mean_sharpe']:.2f} | "
                f"{r['mean_winrate']*100:.1f}% |"
            )

    # Roll-skip blocked log
    lines.append("\n## Roll-skip blocked-signal counts (per user request)\n")
    lines.append("| Symbol | Conf | Eligible bars | Blocked | % blocked | >5% flag |")
    lines.append("|---|---|---|---|---|---|")
    for ir in inst_results:
        for thr in (0.50, 0.65):
            n_b = ir["roll_skip_blocked_signal_count"].get(thr, 0)
            n_e = ir["n_eligible_at_thresholds"].get(thr, 0)
            pct = 100.0 * n_b / max(n_e, 1)
            tag = "⚠️" if pct > 5.0 else "✅"
            lines.append(
                f"| {ir['symbol']} | {thr:.2f} | {n_e:,} | {n_b:,} | "
                f"{pct:.2f}% | {tag} |"
            )

    out_path = reports_dir / "v1_4_phase5_summary.md"
    out_path.write_text("\n".join(lines))
    logger.info(f"wrote {out_path}")


if __name__ == "__main__":
    sys.exit(main())
