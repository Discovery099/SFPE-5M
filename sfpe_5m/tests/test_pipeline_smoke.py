"""Smoke test for the v1 pipeline orchestrator script.

This only verifies importability + module-level wiring; the full pipeline is
exercised via `python scripts/run_pipeline.py` which is invoked separately.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))


def test_imports():
    import sfpe                                      # noqa: F401
    from sfpe.data import loader, integrity, roll_detection, calendar  # noqa: F401
    from sfpe.synthetic import vol_budget, dollar_imbalance, volume_time, range_budget  # noqa: F401
    from sfpe.export import pine_generator           # noqa: F401
    from reporting import plots                      # noqa: F401


def test_pine_generator_blocked():
    from sfpe.export.pine_generator import generate_pine_script
    import pytest
    with pytest.raises(NotImplementedError):
        generate_pine_script()
