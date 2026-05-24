"""Run Phase 1 data audit + integrity + roll detection for all 9 instruments.

Outputs (relative to repo root):
  reports/data_integrity_summary.md
  reports/data_integrity_by_instrument.csv
  reports/roll_candidates.csv
  reports/session_coverage_heatmap.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml
from loguru import logger

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.data.calendar import load_calendars  # noqa: E402
from sfpe.data.loader import load_instrument_csv  # noqa: E402
from sfpe.data.integrity import compute_integrity, session_bars_count  # noqa: E402
from sfpe.data.roll_detection import detect_rolls  # noqa: E402

# we keep the heatmap util as a sibling module under the repo's `reporting/` folder.
sys.path.insert(0, str(REPO))
from reporting.plots import session_coverage_heatmap  # noqa: E402


def _verdict_emoji(v: str) -> str:
    return {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(v, "?")


def main() -> int:
    instruments_yaml = REPO / "config" / "instruments.yaml"
    calendars_yaml = REPO / "config" / "session_calendars.yaml"
    reports_dir = REPO / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    cfg = yaml.safe_load(instruments_yaml.read_text())
    cals = load_calendars(calendars_yaml)

    rows: list[dict] = []
    all_rolls: list[pd.DataFrame] = []
    coverage_by_symbol: dict[str, pd.Series] = {}
    expected_by_symbol: dict[str, int] = {}

    for sym, ic in cfg["instruments"].items():
        csv_path = REPO / ic["file"]
        if not csv_path.exists():
            logger.error(f"{sym}: CSV not found at {csv_path}, skipping.")
            continue
        cal = cals[ic["calendar"]]
        logger.info(f"loading {sym} from {csv_path}  ({cal.name})")
        df = load_instrument_csv(csv_path, cal)
        rep = compute_integrity(
            df,
            symbol=sym,
            expected_bars=cal.expected_bars,
            short_session_threshold_pct=cal.short_session_threshold_pct,
        )
        rows.append(rep)
        logger.info(
            f"  {sym}: n_bars={rep['n_bars']:,} sessions={rep['n_sessions']:,} "
            f"verdict={rep['verdict']}"
        )

        rolls = detect_rolls(df, family=ic["family"])
        if not rolls.empty:
            all_rolls.append(rolls)
            logger.info(f"  {sym}: {len(rolls):,} roll candidates flagged")

        coverage_by_symbol[sym] = session_bars_count(df)
        expected_by_symbol[sym] = cal.expected_bars

    # CSV table
    df_rep = pd.DataFrame(rows)
    by_inst_path = reports_dir / "data_integrity_by_instrument.csv"
    df_rep.to_csv(by_inst_path, index=False)
    logger.info(f"wrote {by_inst_path}")

    # roll candidates
    if all_rolls:
        rolls_all = pd.concat(all_rolls, ignore_index=True)
    else:
        rolls_all = pd.DataFrame(columns=[
            "symbol", "date_prev", "date_next", "close_prev", "open_next",
            "gap", "gap_atr_mult",
        ])
    rolls_path = reports_dir / "roll_candidates.csv"
    rolls_all.to_csv(rolls_path, index=False)
    logger.info(f"wrote {rolls_path}  ({len(rolls_all):,} candidates total)")

    # heatmap
    heatmap_path = reports_dir / "session_coverage_heatmap.png"
    session_coverage_heatmap(coverage_by_symbol, expected_by_symbol, heatmap_path)
    logger.info(f"wrote {heatmap_path}")

    # one-page markdown summary
    md_path = reports_dir / "data_integrity_summary.md"
    lines = [
        "# SFPE-5M  —  Data Integrity Summary (Phase 1)\n",
        f"Total instruments processed: **{len(rows)}**\n",
        f"Total roll candidates flagged: **{len(rolls_all):,}**\n",
        "\n## Per-instrument verdict\n",
        "| Symbol | Calendar | Bars | Sessions | Median bars/sess | Dups | OHLC viol | Bad vol | Zero-vol | Outliers | Missing gaps | Short sess | Out-of-RTH | Verdict |",
        "|--------|----------|------|----------|------------------|------|-----------|---------|----------|----------|--------------|------------|------------|---------|",
    ]
    for r in rows:
        cal_name = cfg["instruments"][r["symbol"]]["calendar"]
        lines.append(
            f"| {r['symbol']} | {cal_name} | {r['n_bars']:,} | {r['n_sessions']:,} | "
            f"{r['median_bars_per_session']} | {r['duplicates']} | {r['ohlc_violations']} | "
            f"{r['bad_volume']} | {r['zero_volume_bars']} | {r['outlier_bars']} | "
            f"{r['missing_gaps']} | {r['short_sessions']} | {r['out_of_rth_bars']} | "
            f"{_verdict_emoji(r['verdict'])} {r['verdict']} |"
        )
    lines.append("\n## Notes\n")
    for r in rows:
        if r.get("notes"):
            lines.append(f"- **{r['symbol']}**: {r['notes']}")
    lines.append("\n## Roll candidates\n")
    if not rolls_all.empty:
        per_sym = rolls_all.groupby("symbol").size().to_dict()
        for sym, cnt in sorted(per_sym.items()):
            lines.append(f"- **{sym}**: {cnt:,} roll candidates (close→open gap > 5 × ATR_20). See `roll_candidates.csv`.")
    else:
        lines.append("- (no candidates flagged)")
    lines.append("\n## Acceptance gate verdict\n")
    any_fail = any(r["verdict"] == "FAIL" for r in rows)
    if any_fail:
        lines.append("❌ **FAIL** — at least one instrument has duplicates / OHLC violations / bad volume. Investigate before proceeding to engines.\n")
    else:
        lines.append("✅ **PASS / WARN** — no hard-failure conditions detected. Safe to proceed to Phase 2 engines.\n")
    md_path.write_text("\n".join(lines))
    logger.info(f"wrote {md_path}")

    return 0 if not any_fail else 1


if __name__ == "__main__":
    sys.exit(main())
