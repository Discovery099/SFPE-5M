"""End-to-end v1 pipeline.

Runs:
  1. data audit  (scripts/run_data_audit.py)
  2. priority engines for ALL instruments  (scripts/run_engines.py)
  3. writes reports/v1_summary.md with the consolidated v1 verdict.

Exit code 0 if both audit and engines pass; else 1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from loguru import logger

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from scripts.run_data_audit import main as audit_main  # noqa: E402
from scripts.run_engines import main as engines_main  # noqa: E402


def main() -> int:
    logger.info("== Phase 1: Data audit ==")
    audit_rc = audit_main()
    logger.info("== Phase 2: Priority synthetic engines ==")
    sys.argv = ["run_engines.py"]  # use defaults: all symbols, both engines
    engines_rc = engines_main()

    reports_dir = REPO / "reports"
    summary_path = reports_dir / "v1_summary.md"
    integrity_csv = reports_dir / "data_integrity_by_instrument.csv"
    engines_csv = reports_dir / "engine_diagnostics" / "engines_summary.csv"

    lines = ["# SFPE-5M  —  v1.1 Pipeline Summary\n",
             "_v1.1 applies Spec Amendments 1 (autocorrelation gate) and 2 (per-family bands per §11.1). See BLOCKERS.md §12–§15._\n"]
    if integrity_csv.exists():
        ddf = pd.read_csv(integrity_csv)
        lines.append("## Phase 1 — Data audit\n")
        lines.append(f"Instruments processed: **{len(ddf)}**  ")
        lines.append(f"PASS: **{int((ddf['verdict']=='PASS').sum())}**  \n"
                     f"WARN: **{int((ddf['verdict']=='WARN').sum())}**  \n"
                     f"FAIL: **{int((ddf['verdict']=='FAIL').sum())}**\n")
        lines.append("See `reports/data_integrity_summary.md` for the full table.\n")
        lines.append("> **Note (deferred):** the `roll_candidates.csv` count is currently over-flagged (~4,551). The detector multiplier + calendar + volume-signature upgrade is documented in `BLOCKERS.md §9` and will land before the Phase 5 backtest cycle.\n")
    if engines_csv.exists():
        edf = pd.read_csv(engines_csv)
        lines.append("## Phase 2 — All four synthetic engines (v1.1)\n")
        lines.append(f"Engine runs: **{len(edf)}** (4 engines × {len(edf)//4} instruments)  ")
        lines.append(f"Gate PASS: **{int(edf['ok'].astype(bool).sum())}**  \n"
                     f"Gate FAIL: **{int((~edf['ok'].astype(bool)).sum())}**\n")
        lines.append("See `reports/engine_diagnostics/` for per-(engine, symbol) diagnostics (asset class + per-family band displayed, source & synthetic lag-1 autocorr displayed, autocorr-gate reason quoted).\n")

    lines.append("## v1.1 verdict\n")
    if audit_rc == 0 and engines_rc == 0:
        lines.append("✅ **PASS** — Phase 1 audit + Phase 2 all four engines pass the v1.1-corrected §11.1 acceptance gates (per-family band + combined autocorr).")
    else:
        lines.append("❌ **FAIL** — at least one phase did not pass. See logs and per-phase reports.")

    lines.append("\n## Deferred to later versions\n")
    lines.append("- Roll-detection multiplier + calendar + volume-signature upgrade (before Phase 5)")
    lines.append("- Phase 3 features (absorption, VPIN proxy, TPO, liquidity vacuum, regime router, magnitude projection)")
    lines.append("- Phase 4 forward projection + ensemble")
    lines.append("- Phase 5 backtest + baselines + cost models")
    lines.append("- Phase 6 walk-forward optimization (fast protocol: 12m / 3m / 3m / 1m)")
    lines.append("- Phase 7 final reporting + PASS/FAIL verdict")
    lines.append("- Phase 8 Pine Script export (only if Phase 7 PASSes)\n")

    summary_path.write_text("\n".join(lines))
    logger.info(f"wrote {summary_path}")

    return 0 if (audit_rc == 0 and engines_rc == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
