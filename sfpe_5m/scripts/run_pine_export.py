"""Generate all Pine v6 export files (per-instrument strategy + indicator + screener).

Owner-locked (BLOCKERS §44): v1.5-final-A_STOP parameters are hardcoded as
defaults. Phase 6 walk-forward was DELIBERATELY NOT RUN. Pine output is for
visual inspection on TradingView live charts, NOT for live trading.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sfpe.pine_exporter import (
    INSTRUMENTS, build_strategy_pine, build_indicator_pine, build_screener_pine,
)


def main() -> int:
    out_dir = REPO / "exports" / "pine"
    out_dir.mkdir(parents=True, exist_ok=True)
    files_written: list[Path] = []

    for sym, ins in INSTRUMENTS.items():
        # Strategy file.
        strat_text = build_strategy_pine(ins)
        strat_path = out_dir / f"sfpe_5m_{sym.lower()}_strategy.pine"
        strat_path.write_text(strat_text)
        files_written.append(strat_path)

        # Indicator file.
        ind_text = build_indicator_pine(ins)
        ind_path = out_dir / f"sfpe_5m_{sym.lower()}_indicator.pine"
        ind_path.write_text(ind_text)
        files_written.append(ind_path)

    # Screener.
    scr_path = out_dir / "sfpe_5m_screener.pine"
    scr_path.write_text(build_screener_pine(INSTRUMENTS))
    files_written.append(scr_path)

    for f in files_written:
        size = f.stat().st_size
        print(f"  wrote {f.relative_to(REPO)}  ({size:,} bytes)")
    print(f"\ntotal {len(files_written)} files; {sum(f.stat().st_size for f in files_written):,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
