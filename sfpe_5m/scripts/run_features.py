"""Run the 6 SFPE-5M Phase-3 features for selected symbols. Writes per-feature
CSVs into features/ and a compact diagnostic summary into reports/feature_diagnostics/.

Usage:
  python scripts/run_features.py                          # all instruments
  python scripts/run_features.py --symbols ES MNQ MGC MCL
  python scripts/run_features.py --features absorption regime
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml
from loguru import logger

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from sfpe.data.calendar import load_calendars  # noqa: E402
from sfpe.data.loader import load_instrument_csv  # noqa: E402
from sfpe.features.absorption import compute_absorption  # noqa: E402
from sfpe.features.liquidity_vacuum import compute_vacuum  # noqa: E402
from sfpe.features.regime_router import compute_regime  # noqa: E402
from sfpe.features.vpin_proxy import compute_vpin  # noqa: E402
from sfpe.features.tpo_profile import compute_tpo  # noqa: E402
from sfpe.features.magnitude_projection import compute_magnitude_projection  # noqa: E402
from sfpe.synthetic.vol_budget import VolBudgetEngine  # noqa: E402
from sfpe.synthetic.dollar_imbalance import DollarImbalanceEngine  # noqa: E402
from sfpe.synthetic.volume_time import VolumeTimeEngine  # noqa: E402
from sfpe.synthetic.range_budget import RangeBudgetEngine  # noqa: E402
from sfpe.synthetic.base import bars_to_dataframe  # noqa: E402
from sfpe.data.families import target_bars_for_family, asset_class_of  # noqa: E402

FEATURES_ALL = ["absorption", "vacuum", "regime", "vpin", "tpo", "magnitude_projection"]

ENGINES = {
    "vol_budget": VolBudgetEngine,
    "dollar_imbalance": DollarImbalanceEngine,
    "volume_time": VolumeTimeEngine,
    "range_budget": RangeBudgetEngine,
}

RANGE_K_BY_FAMILY = {"equity": 1.5, "commodity": 1.5}


def _run_engine(engine_name: str, df: pd.DataFrame, sym: str, ic: dict, cal) -> pd.DataFrame:
    engine = ENGINES[engine_name]()
    family = ic["family"]
    asset_class = asset_class_of(family)
    target_bars = target_bars_for_family(family)
    if engine_name == "vol_budget":
        bars = engine.run(df, symbol=sym, target_bars_per_session=target_bars,
                          variance_lookback_sessions=20, sigma_mult=1.0,
                          variance_proxy="parkinson",
                          min_source_bars=1, max_source_bars=cal.expected_bars)
    elif engine_name == "dollar_imbalance":
        bars = engine.run(df, symbol=sym, point_value=float(ic["point_value"]),
                          imbalance_window=50, theta_mult=1.0,
                          target_bars_per_session=target_bars,
                          expected_bars_per_session=cal.expected_bars,
                          min_source_bars=1, max_source_bars=cal.expected_bars)
    elif engine_name == "volume_time":
        bars = engine.run(df, symbol=sym, target_bars_per_session=target_bars,
                          session_volume_lookback=20,
                          min_source_bars=1, max_source_bars=cal.expected_bars)
    else:
        bars = engine.run(df, symbol=sym, range_k=RANGE_K_BY_FAMILY[asset_class],
                          min_source_bars=1, max_source_bars=cal.expected_bars)
    return bars_to_dataframe(bars)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--features", nargs="*", default=FEATURES_ALL,
                    choices=FEATURES_ALL)
    ap.add_argument("--engines-for-magnitude", nargs="*", default=["vol_budget"],
                    choices=list(ENGINES.keys()))
    args = ap.parse_args()

    cfg = yaml.safe_load((REPO / "config" / "instruments.yaml").read_text())
    cals = load_calendars(REPO / "config" / "session_calendars.yaml")

    syms = args.symbols if args.symbols else list(cfg["instruments"].keys())
    feat_dir = REPO / "features"
    diag_dir = REPO / "reports" / "feature_diagnostics"
    feat_dir.mkdir(parents=True, exist_ok=True)
    diag_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = []

    for sym in syms:
        ic = cfg["instruments"][sym]
        cal = cals[ic["calendar"]]
        family = ic["family"]
        tick = float(ic["tick_size"])
        logger.info(f"{sym}: loading source bars ({cal.name})")
        df = load_instrument_csv(REPO / ic["file"], cal)

        per_sym_features: dict[str, pd.DataFrame] = {}

        if "absorption" in args.features:
            logger.info(f"{sym}: absorption")
            a = compute_absorption(df, family=family, tick_size=tick)
            per_sym_features["absorption"] = a
            a.to_csv(feat_dir / f"absorption__{sym}.csv", index=False)
            summary_rows.append(dict(symbol=sym, feature="absorption",
                                     flagged=int(a["absorption_flag"].sum()),
                                     pct_flagged=float(a["absorption_flag"].mean()*100)))
        if "vacuum" in args.features:
            logger.info(f"{sym}: vacuum")
            v = compute_vacuum(df, family=family)
            per_sym_features["vacuum"] = v
            v.to_csv(feat_dir / f"vacuum__{sym}.csv", index=False)
            summary_rows.append(dict(symbol=sym, feature="vacuum",
                                     flagged=int(v["vacuum_flag"].sum()),
                                     pct_flagged=float(v["vacuum_flag"].mean()*100)))
        if "regime" in args.features:
            logger.info(f"{sym}: regime")
            r = compute_regime(df)
            per_sym_features["regime"] = r
            r.to_csv(feat_dir / f"regime__{sym}.csv", index=False)
            non_sd = int((r["regime_label"] != "stand_down").sum())
            summary_rows.append(dict(symbol=sym, feature="regime",
                                     flagged=non_sd,
                                     pct_flagged=float(non_sd/len(r)*100)))
        if "vpin" in args.features:
            logger.info(f"{sym}: vpin")
            vp = compute_vpin(df, tick_size=tick)
            per_sym_features["vpin"] = vp
            vp.to_csv(feat_dir / f"vpin__{sym}.csv", index=False)
            sd = int((vp["gate_decision"] == "stand_down").sum())
            summary_rows.append(dict(symbol=sym, feature="vpin",
                                     flagged=sd,
                                     pct_flagged=float(sd/len(vp)*100)))
        if "tpo" in args.features:
            logger.info(f"{sym}: tpo")
            tpo = compute_tpo(df, tick_size=tick)
            per_sym_features["tpo"] = tpo
            tpo.to_csv(feat_dir / f"tpo__{sym}.csv", index=False)
            fa = int(tpo["failed_auction_flag"].sum())
            summary_rows.append(dict(symbol=sym, feature="tpo",
                                     flagged=fa,
                                     pct_flagged=float(fa/len(tpo)*100)))
        if "magnitude_projection" in args.features:
            if not all(k in per_sym_features for k in ["absorption", "vacuum", "regime", "vpin", "tpo"]):
                logger.warning(f"{sym}: magnitude_projection requires the other 5 features; skipping")
            else:
                for eng_name in args.engines_for_magnitude:
                    logger.info(f"{sym}: magnitude_projection on engine={eng_name}")
                    bdf = _run_engine(eng_name, df, sym, ic, cal)
                    if bdf.empty:
                        continue
                    mp = compute_magnitude_projection(
                        bdf, source_df=df,
                        feature_regime=per_sym_features["regime"],
                        feature_vpin=per_sym_features["vpin"],
                        feature_absorption=per_sym_features["absorption"],
                        feature_vacuum=per_sym_features["vacuum"],
                        feature_tpo=per_sym_features["tpo"],
                        expected_bars_per_session=cal.expected_bars,
                    )
                    out = pd.concat([bdf.reset_index(drop=True),
                                     mp.reset_index(drop=True)], axis=1)
                    out.to_csv(feat_dir / f"magnitude_projection__{eng_name}__{sym}.csv",
                               index=False)
                    summary_rows.append(dict(
                        symbol=sym, feature=f"magnitude_projection({eng_name})",
                        flagged=int((mp["pooling_level"] >= 0).sum()),
                        pct_flagged=float((mp["pooling_level"] >= 0).mean()*100),
                    ))

    if summary_rows:
        sumdf = pd.DataFrame(summary_rows)
        sum_path = diag_dir / "features_summary.csv"
        sumdf.to_csv(sum_path, index=False)
        logger.info(f"wrote feature summary: {sum_path}")
        # markdown
        lines = ["# SFPE-5M  —  Feature Diagnostics\n",
                 "| Symbol | Feature | Flagged / Non-stand_down | % of bars |",
                 "|--------|---------|---------------------------|-----------|"]
        for r in summary_rows:
            lines.append(f"| {r['symbol']} | {r['feature']} | {r['flagged']:,} | {r['pct_flagged']:.2f}% |")
        (diag_dir / "features_summary.md").write_text("\n".join(lines))

    return 0


if __name__ == "__main__":
    sys.exit(main())
