"""Phase 6 master walk-forward driver.

Runs walk_forward_one_instrument across all 9 instruments. Writes:
  reports/v1_6/per_instrument__<SYM>__folds.csv
  reports/v1_6/per_instrument__<SYM>__selected.csv
  reports/v1_6_walkforward.md
  reports/v1_6_selected_params.csv         # one row per instrument with final params
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from loguru import logger

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.walk_forward import (
    walk_forward_one_instrument, aggregate_selected_params_for_export, GRID,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None,
                     help="restrict to a subset of symbols (default all 9)")
    args = ap.parse_args()

    out_dir = REPO / "reports" / "v1_6"
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = REPO / "reports"

    cfg = yaml.safe_load((REPO / "config" / "instruments.yaml").read_text())
    syms = args.symbols if args.symbols else list(cfg["instruments"].keys())

    per_instr_summary_rows: list[dict] = []
    selected_export_rows: list[dict] = []
    all_folds_rows: list[dict] = []

    for sym in syms:
        logger.info(f"=== walk-forward: {sym} ===")
        try:
            wf = walk_forward_one_instrument(symbol=sym, repo=REPO)
        except Exception as e:
            logger.exception(f"{sym} failed: {e}")
            continue
        logger.info(f"  {sym}: folds={wf['n_folds']} variants={wf['n_trials']} "
                    f"PBO={wf['pbo']:.3f} DSR={wf['deflated_sharpe']:.3f} "
                    f"mean_oos_sharpe={wf['mean_oos_sharpe']:.3f}")

        # Per-instrument CSVs.
        sel = pd.DataFrame(wf["selected_per_fold"])
        if not sel.empty:
            sel.to_csv(out_dir / f"per_instrument__{sym}__selected.csv", index=False)
        folds_df = pd.DataFrame(wf["fold_results"])
        if not folds_df.empty:
            folds_df.to_csv(out_dir / f"per_instrument__{sym}__folds.csv", index=False)
            all_folds_rows.extend(wf["fold_results"])

        # Aggregate "final" params for Pine export.
        final_params = aggregate_selected_params_for_export(wf["selected_per_fold"])
        selected_export_rows.append(dict(
            symbol=sym,
            structural_buffer_atr_mult=final_params["buf"],
            projection_hold_mult=final_params["hold_mult"],
            tp1_partial_fraction=final_params["partial"],
            min_confidence=final_params["conf"],
            min_engines_agree=3,
            risk_per_trade=0.005,
            n_folds=wf["n_folds"],
            n_trials=wf["n_trials"],
            pbo=wf["pbo"],
            deflated_sharpe=wf["deflated_sharpe"],
            mean_oos_sharpe=wf["mean_oos_sharpe"],
            mean_oos_pf=float(sel["oos_pf"].replace([np.inf, -np.inf], np.nan).mean()) if not sel.empty else float("nan"),
            mean_oos_net=float(sel["oos_net"].mean()) if not sel.empty else 0.0,
            mean_oos_trades=float(sel["oos_n_trades"].mean()) if not sel.empty else 0.0,
            sum_oos_net=float(sel["oos_net"].sum()) if not sel.empty else 0.0,
            sum_oos_trades=int(sel["oos_n_trades"].sum()) if not sel.empty else 0,
        ))
        per_instr_summary_rows.append(dict(
            symbol=sym,
            **final_params,
            n_folds=wf["n_folds"],
            pbo=wf["pbo"],
            dsr=wf["deflated_sharpe"],
            mean_oos_sharpe=wf["mean_oos_sharpe"],
        ))

    # Master selected-params CSV (consumed by Pine exporter).
    selected_df = pd.DataFrame(selected_export_rows)
    selected_df.to_csv(reports_dir / "v1_6_selected_params.csv", index=False)
    logger.info(f"wrote {reports_dir / 'v1_6_selected_params.csv'}  rows={len(selected_df)}")

    write_walkforward_md(
        selected=selected_df,
        all_folds=pd.DataFrame(all_folds_rows),
        out_path=reports_dir / "v1_6_walkforward.md",
    )
    return 0


def write_walkforward_md(*, selected: pd.DataFrame, all_folds: pd.DataFrame,
                          out_path: Path) -> None:
    lines: list[str] = []
    lines.append("# SFPE-5M Phase 6 — Walk-Forward Optimization v1.6\n")
    lines.append(
        "_Owner override of v1.5-final-A_STOP (BLOCKERS §44). Compute-reduced grid: "
        "structural_buffer ∈ {0.5,1.0,2.0} × hold_mult ∈ {1.5,3.0} × partial fixed "
        "at 0.5 × conf ∈ {0.50,0.65} × engines_agree fixed at 3 × risk fixed at 0.005 = "
        "**12 combos**. 6-month step, 12 m train + 3 m val + 3 m test per fold.  "
        "Per-instrument optimisation, no portfolio aggregation._\n"
    )
    lines.append("\n## Per-instrument selected parameters + OOS metrics\n")
    lines.append("| Symbol | buf | hold_mult | partial | conf | n_folds | PBO | DSR | mean OOS Sharpe | mean OOS PF | sum OOS net | sum OOS trades |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for _, r in selected.iterrows():
        lines.append(
            f"| {r['symbol']} | {r['structural_buffer_atr_mult']:.1f} | "
            f"{r['projection_hold_mult']:.1f} | {r['tp1_partial_fraction']:.1f} | "
            f"{r['min_confidence']:.2f} | {int(r['n_folds'])} | "
            f"{r['pbo']:.2f} | {r['deflated_sharpe']:.2f} | "
            f"{r['mean_oos_sharpe']:.2f} | {r['mean_oos_pf']:.2f} | "
            f"{r['sum_oos_net']:,.0f} | {int(r['sum_oos_trades']):,} |"
        )

    # Honest verdict line.
    n_inst_pf_above_1 = int((selected["mean_oos_pf"].fillna(0) > 1.0).sum())
    n_inst_net_positive = int((selected["sum_oos_net"].fillna(0) > 0).sum())
    n_inst_dsr_above_0 = int((selected["deflated_sharpe"].fillna(-99) > 0).sum())
    lines.append("\n## Honest OOS verdict (across 9 instruments)\n")
    lines.append(f"- Instruments with mean OOS PF > 1.0: **{n_inst_pf_above_1} / 9**")
    lines.append(f"- Instruments with sum OOS net > 0: **{n_inst_net_positive} / 9**")
    lines.append(f"- Instruments with DSR > 0: **{n_inst_dsr_above_0} / 9**")
    median_pbo = float(selected["pbo"].median())
    lines.append(f"- Median PBO across instruments: **{median_pbo:.2f}** "
                  f"(0.0 = no overfit, 1.0 = severe overfit; >0.5 strongly indicates overfitting).")

    # Fold-level honesty
    if not all_folds.empty:
        oos_winning_folds = int((all_folds["oos_net"].fillna(0) > 0).sum())
        total_folds = len(all_folds)
        lines.append(f"- Total (instrument × fold × variant) OOS observations: {total_folds:,}; "
                      f"profitable: {oos_winning_folds:,} ({100*oos_winning_folds/max(total_folds,1):.1f}%).")

    lines.append("\n## Caveats and overrides logged in BLOCKERS §44\n")
    lines.append("- Compute-reduced grid (12 combos) vs the listed 2,160-combo grid.")
    lines.append("- Step = 6 months vs requested 1 month.")
    lines.append("- These reductions are documented in BLOCKERS §44; results below are conditional on them.")
    lines.append("- Phase 5.5 forensic verdict A_STOP stands as the in-sample evidence; Phase 6 is an explicit owner override to test live (Phase 8 Pine).")

    out_path.write_text("\n".join(lines))
    logger.info(f"wrote {out_path}")


if __name__ == "__main__":
    sys.exit(main())
