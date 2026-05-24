"""Three cost models per spec §9.2.

Each returns DOLLAR COST per round-trip trade. Slippage multiplier is applied
separately in the engine (per-leg, on entry and exit fill prices).
"""
from __future__ import annotations

import math


def fixed_tick_cost(
    *, entry_row: dict, exit_row: dict, contracts: int,
    tick_size: float, tick_value: float, point_value: float,
    n_ticks_per_leg: float = 1.0,
) -> float:
    """Fixed-tick cost: 2 legs × n_ticks × tick_value × contracts."""
    return 2.0 * n_ticks_per_leg * tick_value * contracts


def roll_spread_half_spread(
    *, entry_row: dict, exit_row: dict, contracts: int,
    tick_size: float, tick_value: float, point_value: float,
) -> float:
    """Roll-spread proxy: half_spread = sqrt(max(-cov(dprice_t, dprice_{t-1}), 0))
    The covariance is looked up via `entry_row['roll_spread']` (which we supply
    as the regime feature's `roll_spread_proxy` at entry time). Applied as
    half-spread (in PRICE units) per leg, multiplied by point_value and contracts.
    """
    half_spread_price = float(entry_row.get("roll_spread", 0) or 0)
    return 2.0 * half_spread_price * point_value * contracts


def impact_cost(
    *, entry_row: dict, exit_row: dict, contracts: int,
    tick_size: float, tick_value: float, point_value: float,
    impact_mult: float = 0.5,
) -> float:
    """Impact proxy: impact_per_contract = impact_mult * |return_t| / max(volume_t, 1).
    Note: |return_t| here is price_return (close - prev_close at entry bar).
    Total cost = 2 legs × impact_per_contract × point_value × contracts.
    """
    ret = abs(float(entry_row.get("price_return", 0) or 0))
    vol = max(float(entry_row.get("volume", 1) or 1), 1.0)
    impact_per_contract = impact_mult * ret / vol     # in PRICE units per contract
    return 2.0 * impact_per_contract * point_value * contracts


ALL_COST_MODELS = {
    "fixed_tick": fixed_tick_cost,
    "roll_spread": roll_spread_half_spread,
    "impact": impact_cost,
}
