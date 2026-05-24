"""Run the SFPE-5M projection pipeline for selected symbols.

Writes:
  features/projection_ensemble__<symbol>.csv
  features/projection_engine__<engine>__<symbol>.csv  (4 per symbol)

Usage:
  python scripts/run_projection.py                # all 9 instruments
  python scripts/run_projection.py --symbols ES MGC
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.projection.projector import build_projections_for_symbol  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    args = ap.parse_args()

    cfg = yaml.safe_load((REPO / "config" / "instruments.yaml").read_text())
    syms = args.symbols if args.symbols else list(cfg["instruments"].keys())

    for sym in syms:
        logger.info(f"=== projections for {sym} ===")
        ens, per_eng = build_projections_for_symbol(sym, repo_root=REPO, write_outputs=True)
        n_elig = int(ens["trade_eligible"].sum())
        n_high = int((ens["ensemble_confidence"] >= 0.65).sum())
        logger.info(f"{sym}: rows={len(ens):,} trade_eligible={n_elig:,} "
                    f"conf>=0.65={n_high:,} override_applied={int(ens['override_applied'].sum()):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
