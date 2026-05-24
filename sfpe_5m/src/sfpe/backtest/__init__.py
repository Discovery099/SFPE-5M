# SFPE-5M backtest layer (spec §9).
# v1.4 implementation.
from .event_engine import (
    Trade, EventEngine, BacktestParams, BacktestResult,
)
from .cost_models import (
    fixed_tick_cost, roll_spread_half_spread, impact_cost, ALL_COST_MODELS,
)
from .metrics import compute_metrics, regime_breakdown
from .baselines import (
    buy_and_hold_intraday, prior_bar_momentum, prior_bar_mean_reversion,
    atr_breakout, vwap_mean_reversion, opening_range_breakout,
    random_entry_matched_holding,
    BASELINES,
)

__all__ = [
    "Trade", "EventEngine", "BacktestParams", "BacktestResult",
    "fixed_tick_cost", "roll_spread_half_spread", "impact_cost", "ALL_COST_MODELS",
    "compute_metrics", "regime_breakdown",
    "buy_and_hold_intraday", "prior_bar_momentum", "prior_bar_mean_reversion",
    "atr_breakout", "vwap_mean_reversion", "opening_range_breakout",
    "random_entry_matched_holding",
    "BASELINES",
]
