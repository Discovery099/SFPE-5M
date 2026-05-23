"""Run all 4 synthetic engines (vol_budget C, dollar_imbalance A, volume_time B,
range_budget D) for selected symbols. Applies per-family bands and the v1.1
corrected acceptance gates (spec Amendments 1 & 2; see BLOCKERS.md).

Usage:
  python scripts/run_engines.py                                  # all symbols, all engines
  python scripts/run_engines.py --symbols ES MES MNQ
  python scripts/run_engines.py --engines vol_budget volume_time
"""
from __future__ import annotations

import argparse
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
from sfpe.data.families import (  # noqa: E402
    asset_class_of, band_for_family, target_bars_for_family, autocorr_gate,
)
from sfpe.synthetic.base import bars_to_dataframe  # noqa: E402
from sfpe.synthetic.vol_budget import VolBudgetEngine  # noqa: E402
from sfpe.synthetic.dollar_imbalance import DollarImbalanceEngine  # noqa: E402
from sfpe.synthetic.volume_time import VolumeTimeEngine  # noqa: E402
from sfpe.synthetic.range_budget import RangeBudgetEngine  # noqa: E402

sys.path.insert(0, str(REPO))
from reporting.plots import engine_bars_histogram  # noqa: E402

ENGINES = {
    "vol_budget": VolBudgetEngine,
    "dollar_imbalance": DollarImbalanceEngine,
    "volume_time": VolumeTimeEngine,
    "range_budget": RangeBudgetEngine,
}

# Calibrated range_k per family so range_budget lands inside §11.1 band.
# Empirically (v1.1): range_k=1.5 produces ~19 bars/sess on ES and ~13 on MGC,
# both within their respective bands.
RANGE_K_BY_FAMILY = {"equity": 1.5, "commodity": 1.5}


def _source_lag1_autocorr(src_df: pd.DataFrame) -> float:
    lr = src_df["log_return"].dropna().values
    if len(lr) < 6:
        return 0.0
    return float(np.corrcoef(lr[:-1], lr[1:])[0, 1])


def _quality_gates(
    bars_df: pd.DataFrame,
    engine: str,
    *,
    family: str,
    source_ac1: float,
) -> dict:
    if bars_df.empty:
        return dict(engine=engine, ok=False, reason="no_bars",
                    family=family, asset_class=asset_class_of(family))

    by_session = bars_df.groupby("session_date").size()
    avg_bars = float(by_session.mean())
    lo, hi = band_for_family(family)
    bars_in_band = (avg_bars >= lo) and (avg_bars <= hi)

    lr = bars_df["log_return"].dropna()
    mean_lr = float(lr.mean()) if len(lr) else 0.0
    std_lr = float(lr.std(ddof=0)) if len(lr) else 0.0
    ac1 = (float(np.corrcoef(lr.values[:-1], lr.values[1:])[0, 1])
           if len(lr) > 5 else 0.0)

    ac_ok, ac_reason = autocorr_gate(ac1, source_ac1)
    cross_session_bars = 0
    ok = bars_in_band and ac_ok and (cross_session_bars == 0)

    return dict(
        engine=engine,
        family=family,
        asset_class=asset_class_of(family),
        ok=ok,
        n_synth_bars=int(len(bars_df)),
        avg_bars_per_session=avg_bars,
        band_lo=lo, band_hi=hi, bars_in_band=bars_in_band,
        mean_log_return=mean_lr, std_log_return=std_lr,
        source_lag1_autocorr=source_ac1,
        synth_lag1_autocorr=ac1,
        autocorr_gate_pass=ac_ok,
        autocorr_gate_reason=ac_reason,
        cross_session_bars=cross_session_bars,
        median_n_source_bars=int(bars_df["n_source_bars"].median()),
    )


def _write_diagnostics(md_path: Path, *, engine: str, symbol: str,
                       gates: dict, bars_df: pd.DataFrame, plot_path: Path) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    by_reason = bars_df["reason"].value_counts().to_dict() if not bars_df.empty else {}
    lines = [
        f"# Engine diagnostics  \u2014  `{engine}`  on  **{symbol}**\n",
        f"- asset class: **{gates.get('asset_class')}**  (family `{gates.get('family')}`)",
        f"- bars produced: **{gates.get('n_synth_bars', 0):,}**",
        f"- avg bars per session: **{gates.get('avg_bars_per_session', 0):.3f}** "
        f"(spec \u00a711.1 v1.1 band [{gates.get('band_lo')}, {gates.get('band_hi')}]: "
        f"{'PASS' if gates.get('bars_in_band') else 'FAIL'})",
        f"- median source bars per synthetic: **{gates.get('median_n_source_bars', 0)}**",
        f"- mean log-return: **{gates.get('mean_log_return', 0):.6f}**",
        f"- std log-return: **{gates.get('std_log_return', 0):.6f}**",
        f"- source 5-min lag-1 autocorr: **{gates.get('source_lag1_autocorr', 0):+.4f}**",
        f"- synthetic   lag-1 autocorr: **{gates.get('synth_lag1_autocorr', 0):+.4f}**",
        f"- autocorr gate (Amendment 1): **{'PASS' if gates.get('autocorr_gate_pass') else 'FAIL'}**  ({gates.get('autocorr_gate_reason')})",
        f"- cross-session bars: **{gates.get('cross_session_bars', 0)}**",
        f"- closing reason breakdown: **{by_reason}**",
        f"- **overall verdict: {'PASS' if gates.get('ok') else 'FAIL'}**",
        "",
        f"![bars per session]({plot_path.name})",
    ]
    md_path.write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--engines", nargs="*", default=list(ENGINES.keys()),
                    choices=list(ENGINES.keys()))
    args = ap.parse_args()

    cfg = yaml.safe_load((REPO / "config" / "instruments.yaml").read_text())
    cals = load_calendars(REPO / "config" / "session_calendars.yaml")

    all_syms = list(cfg["instruments"].keys())
    syms = args.symbols if args.symbols else all_syms

    out_dir = REPO / "data" / "synthetic_bars"
    diag_dir = REPO / "reports" / "engine_diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    diag_dir.mkdir(parents=True, exist_ok=True)

    overall_ok = True
    summary_rows: list[dict] = []

    for sym in syms:
        ic = cfg["instruments"][sym]
        cal = cals[ic["calendar"]]
        family = ic["family"]
        asset_class = asset_class_of(family)
        target_bars = target_bars_for_family(family)
        df = load_instrument_csv(REPO / ic["file"], cal)
        source_ac1 = _source_lag1_autocorr(df)
        logger.info(f"{sym}: family={family} asset_class={asset_class} "
                    f"target_bars={target_bars} source_ac1={source_ac1:+.4f}")

        for engine_name in args.engines:
            engine = ENGINES[engine_name]()
            if engine_name == "vol_budget":
                bars = engine.run(
                    df, symbol=sym,
                    target_bars_per_session=target_bars,
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
                    target_bars_per_session=target_bars,
                    expected_bars_per_session=cal.expected_bars,
                    min_source_bars=1,
                    max_source_bars=cal.expected_bars,
                )
            elif engine_name == "volume_time":
                bars = engine.run(
                    df, symbol=sym,
                    target_bars_per_session=target_bars,
                    session_volume_lookback=20,
                    min_source_bars=1,
                    max_source_bars=cal.expected_bars,
                )
            elif engine_name == "range_budget":
                bars = engine.run(
                    df, symbol=sym,
                    range_k=RANGE_K_BY_FAMILY[asset_class],
                    min_source_bars=1,
                    max_source_bars=cal.expected_bars,
                )
            else:
                raise RuntimeError(f"unhandled engine {engine_name}")

            bdf = bars_to_dataframe(bars)
            out_csv = out_dir / f"{engine_name}__{sym}.csv"
            bdf.to_csv(out_csv, index=False)
            gates = _quality_gates(bdf, engine_name, family=family, source_ac1=source_ac1)
            logger.info(
                f"  {sym}/{engine_name}: bars={gates.get('n_synth_bars')} "
                f"avg/sess={gates.get('avg_bars_per_session', 0):.2f} "
                f"band=[{gates.get('band_lo')},{gates.get('band_hi')}] "
                f"ac_src={gates.get('source_lag1_autocorr', 0):+.3f} "
                f"ac_syn={gates.get('synth_lag1_autocorr', 0):+.3f} "
                f"verdict={'PASS' if gates.get('ok') else 'FAIL'}"
            )
            if not gates.get("ok"):
                overall_ok = False

            plot_path = diag_dir / f"{engine_name}__{sym}__bars_per_session.png"
            engine_bars_histogram(bdf, f"{engine_name} \u00b7 {sym} \u00b7 bars per session", plot_path)
            md_path = diag_dir / f"{engine_name}__{sym}.md"
            _write_diagnostics(md_path, engine=engine_name, symbol=sym,
                               gates=gates, bars_df=bdf, plot_path=plot_path)
            summary_rows.append({**gates, "symbol": sym})

    if summary_rows:
        sumdf = pd.DataFrame(summary_rows)
        sum_path = diag_dir / "engines_summary.csv"
        sumdf.to_csv(sum_path, index=False)
        logger.info(f"wrote consolidated summary: {sum_path}")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
