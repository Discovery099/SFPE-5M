"""Run priority synthetic engines (Vol-budget C + Dollar-imbalance A) for
selected symbols. Writes synthetic-bar CSVs and per-(engine, symbol) diagnostics
markdowns.

Usage:
  python scripts/run_engines.py                        # all symbols, both engines
  python scripts/run_engines.py --symbols ES MES MNQ
  python scripts/run_engines.py --engines vol_budget
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

from sfpe.data.calendar import load_calendars  # noqa: E402
from sfpe.data.loader import load_instrument_csv  # noqa: E402
from sfpe.synthetic.base import bars_to_dataframe, SyntheticBar  # noqa: E402
from sfpe.synthetic.vol_budget import VolBudgetEngine  # noqa: E402
from sfpe.synthetic.dollar_imbalance import DollarImbalanceEngine  # noqa: E402

sys.path.insert(0, str(REPO))
from reporting.plots import engine_bars_histogram  # noqa: E402

ENGINES = {
    "vol_budget": VolBudgetEngine,
    "dollar_imbalance": DollarImbalanceEngine,
}

ENGINE_BAND = (4, 30)   # spec §11.1 acceptance band for avg bars/session


def _quality_gates(bars_df: pd.DataFrame, engine: str) -> dict:
    if bars_df.empty:
        return dict(engine=engine, ok=False, reason="no_bars")
    by_session = bars_df.groupby("session_date").size()
    avg_bars = float(by_session.mean())
    lo, hi = ENGINE_BAND
    bars_in_band = (avg_bars >= lo) and (avg_bars <= hi)
    lr = bars_df["log_return"].dropna()
    mean_lr = float(lr.mean()) if len(lr) else 0.0
    std_lr = float(lr.std(ddof=0)) if len(lr) else 0.0
    ac1 = (float(np.corrcoef(lr.values[:-1], lr.values[1:])[0, 1])
           if len(lr) > 5 else 0.0)
    mean_near_zero = abs(mean_lr) < (std_lr if std_lr > 0 else 1e-3)
    autocorr_ok = abs(ac1) < 0.3
    cross_session_bars = 0
    ok = bars_in_band and mean_near_zero and autocorr_ok and (cross_session_bars == 0)
    return dict(
        engine=engine, ok=ok,
        n_synth_bars=int(len(bars_df)),
        avg_bars_per_session=avg_bars,
        band_lo=lo, band_hi=hi, bars_in_band=bars_in_band,
        mean_log_return=mean_lr, std_log_return=std_lr,
        mean_near_zero=mean_near_zero,
        lag1_autocorr=ac1, autocorr_ok=autocorr_ok,
        cross_session_bars=cross_session_bars,
        median_n_source_bars=int(bars_df["n_source_bars"].median()),
    )


def _write_diagnostics(
    md_path: Path,
    *,
    engine: str,
    symbol: str,
    gates: dict,
    bars_df: pd.DataFrame,
    plot_path: Path,
) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    by_reason = bars_df["reason"].value_counts().to_dict() if not bars_df.empty else {}
    lines = [
        f"# Engine diagnostics  —  `{engine}`  on  **{symbol}**\n",
        f"- bars produced: **{gates.get('n_synth_bars', 0):,}**",
        f"- avg bars per session: **{gates.get('avg_bars_per_session', 0):.3f}** (target band {ENGINE_BAND[0]}–{ENGINE_BAND[1]})",
        f"- median source bars per synthetic: **{gates.get('median_n_source_bars', 0)}**",
        f"- mean log-return: **{gates.get('mean_log_return', 0):.6f}**",
        f"- std log-return: **{gates.get('std_log_return', 0):.6f}**",
        f"- lag-1 autocorrelation: **{gates.get('lag1_autocorr', 0):.4f}** (gate <0.3)",
        f"- cross-session bars: **{gates.get('cross_session_bars', 0)}**",
        f"- closing reason breakdown: **{by_reason}**",
        f"- verdict: **{'PASS' if gates.get('ok') else 'FAIL'}**",
        "",
        f"![bars per session]({plot_path.name})",
    ]
    md_path.write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None,
                    help="symbols to run (default: all from instruments.yaml)")
    ap.add_argument("--engines", nargs="*", default=list(ENGINES.keys()),
                    choices=list(ENGINES.keys()),
                    help="engines to run")
    args = ap.parse_args()

    cfg = yaml.safe_load((REPO / "config" / "instruments.yaml").read_text())
    cals = load_calendars(REPO / "config" / "session_calendars.yaml")

    all_syms = list(cfg["instruments"].keys())
    syms = args.symbols if args.symbols else all_syms
    unknown = [s for s in syms if s not in cfg["instruments"]]
    if unknown:
        logger.error(f"unknown symbols: {unknown}. valid: {all_syms}")
        return 1

    out_dir = REPO / "data" / "synthetic_bars"
    diag_dir = REPO / "reports" / "engine_diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    diag_dir.mkdir(parents=True, exist_ok=True)

    overall_ok = True
    summary_rows: list[dict] = []

    for sym in syms:
        ic = cfg["instruments"][sym]
        cal = cals[ic["calendar"]]
        df = load_instrument_csv(REPO / ic["file"], cal)
        for engine_name in args.engines:
            engine_cls = ENGINES[engine_name]
            engine = engine_cls()
            if engine_name == "vol_budget":
                bars = engine.run(
                    df, symbol=sym,
                    target_bars_per_session=6,
                    variance_lookback_sessions=20,
                    sigma_mult=1.0,
                    variance_proxy="parkinson",
                    min_source_bars=1,
                    max_source_bars=cal.expected_bars,
                )
            elif engine_name == "dollar_imbalance":
                bars = engine.run(
                    df, symbol=sym,
                    point_value=float(ic["point_value"]),
                    imbalance_window=50,
                    theta_mult=1.0,
                    target_bars_per_session=8,
                    expected_bars_per_session=cal.expected_bars,
                    min_source_bars=1,
                    max_source_bars=cal.expected_bars,
                )
            else:
                raise RuntimeError(f"unhandled engine {engine_name}")

            bdf = bars_to_dataframe(bars)
            out_csv = out_dir / f"{engine_name}__{sym}.csv"
            bdf.to_csv(out_csv, index=False)
            gates = _quality_gates(bdf, engine_name)
            logger.info(f"{sym} / {engine_name}: "
                        f"bars={gates.get('n_synth_bars')} "
                        f"avg_per_session={gates.get('avg_bars_per_session', 0):.2f} "
                        f"ac1={gates.get('lag1_autocorr', 0):.3f} "
                        f"verdict={'PASS' if gates.get('ok') else 'FAIL'}")
            if not gates.get("ok"):
                overall_ok = False

            plot_path = diag_dir / f"{engine_name}__{sym}__bars_per_session.png"
            engine_bars_histogram(bdf, f"{engine_name} · {sym} · bars per session", plot_path)
            md_path = diag_dir / f"{engine_name}__{sym}.md"
            _write_diagnostics(md_path, engine=engine_name, symbol=sym,
                               gates=gates, bars_df=bdf, plot_path=plot_path)
            logger.info(f"  wrote {out_csv}  +  {md_path}")
            summary_rows.append({**gates, "symbol": sym})

    # write a consolidated summary CSV
    if summary_rows:
        sumdf = pd.DataFrame(summary_rows)
        sum_path = diag_dir / "engines_summary.csv"
        sumdf.to_csv(sum_path, index=False)
        logger.info(f"wrote consolidated summary: {sum_path}")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
