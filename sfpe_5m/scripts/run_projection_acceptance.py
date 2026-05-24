"""Evaluate Phase-4 acceptance gates (spec §11.2) on every instrument.

Reads:
  features/projection_ensemble__<symbol>.csv
  + completed engine bars to look up realized close/duration per synthetic bar

For each instrument computes:
  - hit_rate_close_in_zone   : at ensemble_conf >= 0.65, % of bars where realized
                                close-at-completion lies in [proj_close_low, proj_close_high]
  - hit_rate_duration_in_zone: same for completion duration in [proj_min, proj_max]
  - monotonicity_score       : Spearman corr of zone_width_atr quintile vs hit rate
                                (negative means narrower zones -> higher hit rate, GOOD)
  - calibration              : 10 confidence buckets x predicted vs realized hit rate

Writes:
  reports/projection_diagnostics/acceptance_by_instrument.csv
  reports/projection_diagnostics/calibration__<symbol>.png
  reports/projection_diagnostics/calibration_summary.md
  reports/projection_diagnostics/joint_pass_rate.md

USAGE:
  python scripts/run_projection_acceptance.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from loguru import logger
from scipy.stats import spearmanr

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.data.calendar import load_calendars  # noqa: E402
from sfpe.data.loader import load_instrument_csv  # noqa: E402
from sfpe.data.families import asset_class_of, target_bars_for_family  # noqa: E402
from sfpe.synthetic.vol_budget import VolBudgetEngine  # noqa: E402
from sfpe.synthetic.dollar_imbalance import DollarImbalanceEngine  # noqa: E402
from sfpe.synthetic.volume_time import VolumeTimeEngine  # noqa: E402
from sfpe.synthetic.range_budget import RangeBudgetEngine  # noqa: E402
from sfpe.synthetic.base import bars_to_dataframe  # noqa: E402

CONFIDENCE_THRESHOLD = 0.65
GATE_HIT_RATE = 0.70
RANGE_K_BY_FAMILY = {"equity": 1.5, "commodity": 1.5}


def _engine_bars(sym, ic, df, cal):
    family = ic["family"]
    asset_class = asset_class_of(family)
    target = target_bars_for_family(family)
    engines = {
        "vol_budget": VolBudgetEngine,
        "dollar_imbalance": DollarImbalanceEngine,
        "volume_time": VolumeTimeEngine,
        "range_budget": RangeBudgetEngine,
    }
    out = {}
    for ename, cls in engines.items():
        engine = cls()
        if ename == "vol_budget":
            bars = engine.run(df, symbol=sym, target_bars_per_session=target,
                              variance_lookback_sessions=20, sigma_mult=1.0,
                              variance_proxy="parkinson",
                              min_source_bars=1, max_source_bars=cal.expected_bars)
        elif ename == "dollar_imbalance":
            bars = engine.run(df, symbol=sym, point_value=float(ic["point_value"]),
                              imbalance_window=50, theta_mult=1.0,
                              target_bars_per_session=target,
                              expected_bars_per_session=cal.expected_bars,
                              min_source_bars=1, max_source_bars=cal.expected_bars)
        elif ename == "volume_time":
            bars = engine.run(df, symbol=sym, target_bars_per_session=target,
                              session_volume_lookback=20,
                              min_source_bars=1, max_source_bars=cal.expected_bars)
        else:
            bars = engine.run(df, symbol=sym, range_k=RANGE_K_BY_FAMILY[asset_class],
                              min_source_bars=1, max_source_bars=cal.expected_bars)
        out[ename] = bars_to_dataframe(bars)
    return out


def _evaluate_symbol(sym: str, cfg: dict, cals: dict, repo: Path) -> dict:
    ic = cfg["instruments"][sym]
    cal = cals[ic["calendar"]]
    ens_csv = repo / "features" / f"projection_ensemble__{sym}.csv"
    if not ens_csv.exists():
        return {"symbol": sym, "error": "ensemble_csv_missing"}
    ens = pd.read_csv(ens_csv, parse_dates=["timestamp"])
    # CSV roundtrip drops tz info; raw values are UTC. Re-attach America/New_York
    # so the latest_entry_time comparison is correct (BLOCKERS §38).
    if ens["timestamp"].dt.tz is None:
        ens["timestamp"] = ens["timestamp"].dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    df = load_instrument_csv(repo / ic["file"], cal)
    bars_by_eng = _engine_bars(sym, ic, df, cal)
    # Use vol_budget bars as the "realized" reference for the hit-rate check.
    # (The ensemble bias must align with this engine's realized close; spec §11.2 says
    # "realized synthetic close" without further qualification — we use the most
    # informative engine = vol_budget per spec build priority §23.)
    vbf = bars_by_eng["vol_budget"].reset_index(drop=True)
    # For each source bar, find the NEXT vol_budget synth that closes AFTER that bar.
    # We'll do this efficiently via a sorted merge.
    close_idxs = vbf["end_idx"].astype(int).values
    close_prices = vbf["close"].astype(float).values
    durations = vbf["n_source_bars"].astype(int).values  # bars in that synth

    # For each ensemble row at source_idx i (i = position in ens), find the next
    # synth bar whose end_idx >= i. Use binary search on close_idxs.
    end_idx_sorted = close_idxs   # already sorted by construction
    realized_close = np.full(len(ens), np.nan, dtype=float)
    realized_dur = np.full(len(ens), np.nan, dtype=float)
    bars_to_realized_close = np.full(len(ens), np.nan, dtype=float)
    for i in range(len(ens)):
        # binary search for first end_idx >= i
        pos = np.searchsorted(end_idx_sorted, i, side="left")
        if pos < len(end_idx_sorted):
            realized_close[i] = close_prices[pos]
            realized_dur[i] = durations[pos]
            bars_to_realized_close[i] = end_idx_sorted[pos] - i + 1
    ens["realized_close"] = realized_close
    ens["realized_completion_bars"] = bars_to_realized_close
    ens["realized_synth_duration"] = realized_dur

    # Gate 1: close-in-zone hit rate at ensemble_conf >= 0.65
    hi_conf = ens[ens["ensemble_confidence"] >= CONFIDENCE_THRESHOLD].copy()
    n_high_conf = int(len(hi_conf))
    if n_high_conf > 0:
        in_zone = ((hi_conf["realized_close"] >= hi_conf["projected_close_low"]) &
                   (hi_conf["realized_close"] <= hi_conf["projected_close_high"]))
        close_hit_rate = float(in_zone.mean())
    else:
        close_hit_rate = float("nan")

    # Gate 2: completion-bars-in-zone hit rate at ensemble_conf >= 0.65
    if n_high_conf > 0:
        dur_in_zone = ((hi_conf["realized_completion_bars"] >= hi_conf["projected_completion_min"]) &
                       (hi_conf["realized_completion_bars"] <= hi_conf["projected_completion_max"]))
        dur_hit_rate = float(dur_in_zone.mean())
    else:
        dur_hit_rate = float("nan")

    # Gate 3: monotonicity of hit rate vs zone_width_atr quintile.
    qq = ens.dropna(subset=["zone_width_atr", "realized_close"]).copy()
    if len(qq) > 100:
        qq["zw_quintile"] = pd.qcut(qq["zone_width_atr"], q=5, duplicates="drop", labels=False)
        in_zone_q = ((qq["realized_close"] >= qq["projected_close_low"]) &
                     (qq["realized_close"] <= qq["projected_close_high"]))
        qq["in_zone"] = in_zone_q.astype(int)
        hit_by_q = qq.groupby("zw_quintile")["in_zone"].mean().sort_index()
        if len(hit_by_q) >= 3:
            rho, _ = spearmanr(hit_by_q.index.values, hit_by_q.values)
            monotonic_negative = bool(rho <= -0.5)
            spearman_rho = float(rho)
        else:
            monotonic_negative = False
            spearman_rho = float("nan")
            hit_by_q = pd.Series(dtype=float)
    else:
        monotonic_negative = False
        spearman_rho = float("nan")
        hit_by_q = pd.Series(dtype=float)

    # Gate 4: Calibration -- 10 confidence buckets vs realized hit rate.
    cb = ens.dropna(subset=["ensemble_confidence", "realized_close"]).copy()
    if len(cb) > 100:
        cb["conf_bucket"] = pd.cut(cb["ensemble_confidence"], bins=np.linspace(0, 1, 11),
                                    include_lowest=True, labels=False)
        in_zone_all = ((cb["realized_close"] >= cb["projected_close_low"]) &
                       (cb["realized_close"] <= cb["projected_close_high"]))
        cb["in_zone"] = in_zone_all.astype(int)
        calib = cb.groupby("conf_bucket").agg(
            n=("in_zone", "size"),
            hit_rate=("in_zone", "mean"),
        )
        calib["midpoint"] = (calib.index + 0.5) / 10.0
    else:
        calib = pd.DataFrame()

    # Joint trade-eligibility decomposition (for owner's question)
    n = len(ens)
    cond_agree = ens["agreement_count"] >= 3
    cond_zone = (ens["zone_overlap_atr"] >= -1e6) & (ens["zone_width_atr"] <= 1.5) & ens["zone_width_atr"].notna()
    cond_horizon = ens["projected_completion_median"] <= max(8, cal.expected_bars // 6)
    cond_vpin = ens["vpin_gate"] != "stand_down"
    cond_regime = ~ens["regime_label"].isin(["stand_down", "stressed_illiquid", "ambiguous"])
    cond_time = ens["timestamp"].dt.time < pd.to_datetime(ic["latest_entry_time"]).time()
    joint = cond_agree & cond_zone & cond_horizon & cond_vpin & cond_regime & cond_time
    pass_rates = dict(
        agree_3of4_pct = float(cond_agree.mean() * 100),
        zone_ok_pct = float(cond_zone.mean() * 100),
        horizon_ok_pct = float(cond_horizon.fillna(False).mean() * 100),
        vpin_ok_pct = float(cond_vpin.mean() * 100),
        regime_ok_pct = float(cond_regime.mean() * 100),
        before_latest_entry_pct = float(cond_time.mean() * 100),
        joint_eligible_pct = float(joint.mean() * 100),
        joint_eligible_count = int(joint.sum()),
    )

    overall_pass = (
        not np.isnan(close_hit_rate) and close_hit_rate >= GATE_HIT_RATE
        and not np.isnan(dur_hit_rate) and dur_hit_rate >= GATE_HIT_RATE
        and monotonic_negative
    )

    return {
        "symbol": sym,
        "family": ic["family"],
        "n_bars": n,
        "n_high_conf": n_high_conf,
        "close_hit_rate_at_conf065": close_hit_rate,
        "duration_hit_rate_at_conf065": dur_hit_rate,
        "zone_width_monotonic_negative": monotonic_negative,
        "spearman_rho_zw_vs_hit": spearman_rho,
        "verdict": "PASS" if overall_pass else "FAIL",
        **pass_rates,
        "_calib": calib,
        "_hit_by_q": hit_by_q,
    }


def main() -> int:
    cfg = yaml.safe_load((REPO / "config" / "instruments.yaml").read_text())
    cals = load_calendars(REPO / "config" / "session_calendars.yaml")
    diag = REPO / "reports" / "projection_diagnostics"
    diag.mkdir(parents=True, exist_ok=True)

    rows = []
    cb_rows = []
    hit_rows = []
    for sym in cfg["instruments"]:
        logger.info(f"evaluating {sym}")
        res = _evaluate_symbol(sym, cfg, cals, REPO)
        if "error" in res:
            logger.warning(f"{sym}: {res['error']}; skipping")
            continue
        calib = res.pop("_calib")
        hit_by_q = res.pop("_hit_by_q")
        rows.append(res)

        # store calibration
        if not calib.empty:
            calib = calib.reset_index().rename(columns={"conf_bucket": "bucket"})
            calib["symbol"] = sym
            cb_rows.append(calib)
            # plot
            fig, ax = plt.subplots(figsize=(7, 5))
            ax.plot([0, 1], [0, 1], "k--", alpha=0.5, label="ideal")
            ax.scatter(calib["midpoint"], calib["hit_rate"], s=calib["n"]/30 + 20)
            ax.set_xlabel("predicted ensemble_confidence (bucket midpoint)")
            ax.set_ylabel("realized hit rate (close-in-zone)")
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.set_title(f"Calibration  —  {sym}  (n_high_conf={res['n_high_conf']:,})")
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            fig.savefig(diag / f"calibration__{sym}.png", dpi=110)
            plt.close(fig)
        if isinstance(hit_by_q, pd.Series) and not hit_by_q.empty:
            for q, v in hit_by_q.items():
                hit_rows.append({"symbol": sym, "zw_quintile": int(q), "hit_rate": float(v)})

    if rows:
        rdf = pd.DataFrame(rows)
        rdf.to_csv(diag / "acceptance_by_instrument.csv", index=False)
        if cb_rows:
            pd.concat(cb_rows, ignore_index=True).to_csv(diag / "calibration_buckets.csv", index=False)
        if hit_rows:
            pd.DataFrame(hit_rows).to_csv(diag / "hit_by_zw_quintile.csv", index=False)

        # acceptance summary md
        passed = int((rdf["verdict"] == "PASS").sum())
        lines = [
            "# Phase 4 Acceptance Gates (spec §11.2)\n",
            f"PASSED {passed} of {len(rdf)} instruments  "
            f"(threshold: ≥5 to authorize Phase 5)\n",
            "| Symbol | Family | n_bars | n_high_conf | close_hit@0.65 | dur_hit@0.65 | zone_monotonic | rho | Verdict |",
            "|--------|--------|--------|-------------|----------------|--------------|-----------------|-----|---------|",
        ]
        for _, r in rdf.iterrows():
            lines.append(
                f"| {r['symbol']} | {r['family']} | {r['n_bars']:,} | {r['n_high_conf']:,} | "
                f"{r['close_hit_rate_at_conf065']:.3f} | {r['duration_hit_rate_at_conf065']:.3f} | "
                f"{r['zone_width_monotonic_negative']} | {r['spearman_rho_zw_vs_hit']:+.3f} | "
                f"{r['verdict']} |"
            )
        (diag / "acceptance_summary.md").write_text("\n".join(lines))

        # joint pass rate report
        jp_lines = [
            "# Joint Trade-Eligibility Pass-Rate (Phase 4 deliverable a/e)\n",
            "Decomposition of the spec §7.4 trade-eligibility conditions on EVERY source bar.\n",
            "| Symbol | Agree3/4 | Zone≤widthATR | Horizon≤k | VPIN¬e tox | Regime¬e SD | Pre-cutoff | Joint | Joint count |",
            "|--------|----------|---------------|-----------|-----------|------------|------------|--------|--------------|",
        ]
        for _, r in rdf.iterrows():
            jp_lines.append(
                f"| {r['symbol']} | {r['agree_3of4_pct']:.1f}% | {r['zone_ok_pct']:.1f}% | "
                f"{r['horizon_ok_pct']:.1f}% | {r['vpin_ok_pct']:.1f}% | {r['regime_ok_pct']:.1f}% | "
                f"{r['before_latest_entry_pct']:.1f}% | **{r['joint_eligible_pct']:.2f}%** | "
                f"{r['joint_eligible_count']:,} |"
            )
        jp_lines.append("\n_Joint = `agree_3of4 AND zone_ok AND horizon_ok AND vpin_ok AND regime_ok AND pre-cutoff`._")
        (diag / "joint_pass_rate.md").write_text("\n".join(jp_lines))

        logger.info(f"acceptance: {passed}/{len(rdf)} instruments PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
