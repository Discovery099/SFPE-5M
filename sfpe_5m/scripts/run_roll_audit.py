"""Phase 5 Step 1 — Roll detection legacy(v1.0) vs v1.4 audit.

User-locked params (2026-05-24):
  - 8× ATR_20 gap
  - Calendar gating to family roll months (BLOCKERS §9)
  - Volume z-score ≥ 0.5 on candidate or prior session
  - ALL three conditions required (require_all_conditions=True)
  - Do NOT auto-tune to hit a target band.

Outputs:
  reports/v1_4_roll_candidates.csv   (all flagged rows, legacy + v1.4, all 9 instruments)
  reports/v1_4_roll_audit.md         (per-instrument before/after summary)
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
from sfpe.data.roll_detection import (  # noqa: E402
    detect_rolls,
    RollDetectionParams,
    ROLL_MONTHS_BY_FAMILY,
)


def main() -> int:
    instruments_yaml = REPO / "config" / "instruments.yaml"
    calendars_yaml = REPO / "config" / "session_calendars.yaml"
    reports_dir = REPO / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    cfg = yaml.safe_load(instruments_yaml.read_text())
    cals = load_calendars(calendars_yaml)

    # User-locked v1.4 params: 8x ATR + calendar + volume zscore, ALL required.
    v14_params = RollDetectionParams(
        atr_mult=8.0,
        days_window=8,
        vol_zscore_min=0.5,
        vol_zscore_lookback=20,
        require_all_conditions=True,
    )

    all_legacy: list[pd.DataFrame] = []
    all_v14: list[pd.DataFrame] = []
    summary_rows: list[dict] = []

    for sym, ic in cfg["instruments"].items():
        csv_path = REPO / ic["file"]
        if not csv_path.exists():
            logger.error(f"{sym}: CSV not found at {csv_path}; skipping")
            continue
        cal = cals[ic["calendar"]]
        family = ic["family"]
        logger.info(f"loading {sym} ({family}) from {csv_path.name}")
        df = load_instrument_csv(csv_path, cal)
        n_sessions = int(df["session_date"].nunique())
        years = (
            pd.Timestamp(df["session_date"].max())
            - pd.Timestamp(df["session_date"].min())
        ).days / 365.25

        # Legacy: 5x ATR only.
        rolls_legacy = detect_rolls(df, family=family, legacy_mode=True)
        rolls_legacy = rolls_legacy.assign(mode="legacy_v1")
        # v1.4: 8x ATR + calendar + volume.
        rolls_v14 = detect_rolls(df, family=family, params=v14_params, legacy_mode=False)
        rolls_v14 = rolls_v14.assign(mode="v1_4")

        legacy_cnt = len(rolls_legacy)
        v14_cnt = len(rolls_v14)
        # Per-quarter expectation for equity quarterly rolls (4/year) or monthly (12/yr for oil)
        expected_per_year = {
            "sp500": 4, "nasdaq": 4, "dow": 4, "russell": 4,
            "gold": 6,            # MGC bi-monthly active months Feb/Apr/Jun/Aug/Oct/Dec
            "oil": 12,            # MCL monthly
        }.get(family, 4)
        expected_rolls = int(round(expected_per_year * years))

        summary_rows.append(dict(
            symbol=sym,
            family=family,
            n_sessions=n_sessions,
            years_covered=round(years, 2),
            expected_per_year=expected_per_year,
            expected_rolls_in_period=expected_rolls,
            legacy_v1_count=legacy_cnt,
            v1_4_count=v14_cnt,
            v1_4_minus_expected=v14_cnt - expected_rolls,
            v1_4_drop_pct=round(100.0 * (legacy_cnt - v14_cnt) / max(legacy_cnt, 1), 2),
            roll_months=",".join(str(m) for m in sorted(
                ROLL_MONTHS_BY_FAMILY.get(family, set()))),
        ))
        if not rolls_legacy.empty:
            all_legacy.append(rolls_legacy)
        if not rolls_v14.empty:
            all_v14.append(rolls_v14)
        logger.info(
            f"  {sym}: legacy={legacy_cnt:,}  v1.4={v14_cnt:,}  "
            f"expected≈{expected_rolls}  drop={summary_rows[-1]['v1_4_drop_pct']:.1f}%"
        )

    # Combine outputs.
    legacy_all = pd.concat(all_legacy, ignore_index=True) if all_legacy else pd.DataFrame()
    v14_all = pd.concat(all_v14, ignore_index=True) if all_v14 else pd.DataFrame()
    combined = pd.concat([legacy_all, v14_all], ignore_index=True)
    out_csv = reports_dir / "v1_4_roll_candidates.csv"
    combined.to_csv(out_csv, index=False)
    logger.info(
        f"wrote {out_csv}  legacy={len(legacy_all):,}  v1.4={len(v14_all):,}"
    )

    # Markdown summary.
    sdf = pd.DataFrame(summary_rows)
    md_path = reports_dir / "v1_4_roll_audit.md"
    lines: list[str] = []
    lines.append("# Phase 5 Step 1 — Roll Detection Audit (legacy v1.0 vs v1.4)\n")
    lines.append(
        "_v1.4 params (user-locked 2026-05-24): **8× ATR_20 gap** + "
        "calendar gating to family roll months + **volume z-score ≥ 0.5** on "
        "candidate or prior session, **ALL three conditions required**._\n"
    )
    lines.append(
        f"_Total flagged candidates — legacy: **{len(legacy_all):,}**, "
        f"v1.4: **{len(v14_all):,}**._\n"
    )
    lines.append("\n## Per-instrument candidate counts\n")
    lines.append(
        "| Symbol | Family | Sessions | Years | Expected/yr | "
        "Expected total | **Legacy v1** | **v1.4** | Drop % | v1.4 − expected |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in summary_rows:
        lines.append(
            f"| {r['symbol']} | {r['family']} | {r['n_sessions']:,} | "
            f"{r['years_covered']} | {r['expected_per_year']} | "
            f"{r['expected_rolls_in_period']} | "
            f"**{r['legacy_v1_count']:,}** | **{r['v1_4_count']:,}** | "
            f"{r['v1_4_drop_pct']:.1f}% | "
            f"{r['v1_4_minus_expected']:+d} |"
        )
    legacy_total = sum(r['legacy_v1_count'] for r in summary_rows)
    v14_total = sum(r['v1_4_count'] for r in summary_rows)
    expected_total = sum(r['expected_rolls_in_period'] for r in summary_rows)
    lines.append(
        f"| **TOTAL** | — | — | — | — | **{expected_total}** | "
        f"**{legacy_total:,}** | **{v14_total:,}** | "
        f"{100.0 * (legacy_total - v14_total) / max(legacy_total, 1):.1f}% | "
        f"{v14_total - expected_total:+d} |"
    )

    # Per-instrument condition contribution
    lines.append("\n## v1.4 per-instrument condition signature (which conditions fired)\n")
    if not v14_all.empty:
        cond_counts = (
            v14_all.groupby(["symbol", "conditions_met"])
            .size().reset_index(name="n")
            .pivot(index="symbol", columns="conditions_met", values="n")
            .fillna(0).astype(int)
        )
        # All v1.4 rows have conditions_met = "gap+cal+vol" because
        # require_all_conditions=True; this is informational.
        # Build markdown manually (avoid tabulate dependency).
        cols = list(cond_counts.columns)
        lines.append("| symbol | " + " | ".join(cols) + " |")
        lines.append("|" + "---|" * (1 + len(cols)))
        for sym, row in cond_counts.iterrows():
            lines.append(f"| {sym} | " + " | ".join(str(int(row[c])) for c in cols) + " |")
    else:
        lines.append("_(no v1.4 flags)_")

    # Verdict block
    lines.append("\n## Acceptance vs principled expectation\n")
    over_band = v14_total > 350
    under_band = v14_total < 150
    if over_band:
        lines.append(
            f"⚠️ **v1.4 total = {v14_total} > 350 (upper of the principled "
            f"150–350 band).** "
            "Per user instruction, we do not auto-tune; we surface the data "
            "and await guidance before proceeding to backtester."
        )
    elif under_band:
        lines.append(
            f"⚠️ **v1.4 total = {v14_total} < 150 (lower of the principled "
            f"150–350 band).** "
            "Per user instruction, we do not auto-tune; surfacing and awaiting "
            "guidance."
        )
    else:
        lines.append(
            f"✅ **v1.4 total = {v14_total}** falls within the principled "
            f"150–350 band.  Drop from legacy v1.0: "
            f"{100.0 * (legacy_total - v14_total) / max(legacy_total, 1):.1f}%."
        )

    # Family-rollmonth reference table
    lines.append("\n## Family roll-month reference\n")
    lines.append("| Family | Roll months |\n|---|---|")
    for fam, months in sorted(ROLL_MONTHS_BY_FAMILY.items()):
        lines.append(f"| {fam} | {','.join(str(m) for m in sorted(months))} |")

    md_path.write_text("\n".join(lines))
    logger.info(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
