"""Per-family asset-class classification and acceptance-gate constants.

Applies SFPE-5M Spec Amendments 1 & 2 (issued 2026-05-23 by the project owner)
to the original spec §11.1 gates.

BLOCKERS.md §12 (Amendment 2) and §13 (Amendment 1) carry the rationale.
"""
from __future__ import annotations

from typing import Tuple

EQUITY_FAMILIES = {"sp500", "nasdaq", "dow", "russell"}
COMMODITY_FAMILIES = {"gold", "oil"}

# Spec Amendment 2 (v1.1): replaces original [10,60]/[8,50] with narrower bands
# better suited to 5-minute source data.
BANDS: dict[str, Tuple[int, int]] = {
    "equity":    (12, 25),   # target ~18
    "commodity": (10, 20),   # target ~14
}

# Target bars per session per family (engine config default).
TARGET_BARS_PER_SESSION: dict[str, int] = {
    "equity":    18,
    "commodity": 14,
}


def asset_class_of(family: str) -> str:
    """Return 'equity' or 'commodity' for an instrument family."""
    if family in EQUITY_FAMILIES:
        return "equity"
    if family in COMMODITY_FAMILIES:
        return "commodity"
    raise ValueError(
        f"unknown instrument family {family!r}; expected one of "
        f"{sorted(EQUITY_FAMILIES | COMMODITY_FAMILIES)}"
    )


def band_for_family(family: str) -> Tuple[int, int]:
    """Return the spec §11.1 (v1.1-amended) bars-per-session band."""
    return BANDS[asset_class_of(family)]


def target_bars_for_family(family: str) -> int:
    return TARGET_BARS_PER_SESSION[asset_class_of(family)]


def autocorr_gate(
    synth_ac1: float,
    source_ac1: float,
    *,
    near_zero_threshold: float = 0.05,
    rel_tol: float = 0.20,
) -> tuple[bool, str]:
    """Spec Amendment 1 (v1.1) combined autocorrelation gate.

    If |source_ac1| >= 0.05:
        pass iff |synth_ac1 - source_ac1| / |source_ac1| <= 0.20
    Else (source autocorr near zero):
        pass iff |synth_ac1| <= 0.05
    """
    if abs(source_ac1) >= near_zero_threshold:
        denom = abs(source_ac1)
        ratio = abs(synth_ac1 - source_ac1) / denom
        ok = ratio <= rel_tol
        reason = (f"|delta|/|src|={ratio:.4f} (src_ac1={source_ac1:+.4f}, "
                  f"synth_ac1={synth_ac1:+.4f}, gate<={rel_tol})")
    else:
        ok = abs(synth_ac1) <= near_zero_threshold
        reason = (f"|synth_ac1|={abs(synth_ac1):.4f} (src near zero "
                  f"|src_ac1|={abs(source_ac1):.4f}, gate<={near_zero_threshold})")
    return ok, reason
