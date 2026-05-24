# SFPE-5M backtest layer (spec §9 + §12).
# v1.4 (Phase 5) implementation.
from .event_engine import (
    Trade, EventEngine, BacktestParams, BacktestResult, trades_to_dataframe,
)
from .cost_models import (
    fixed_tick_cost, roll_spread_half_spread, impact_cost, ALL_COST_MODELS,
)
from .metrics import compute_metrics, regime_breakdown, deflated_sharpe, pbo_score
from .baselines import (
    buy_and_hold_intraday, prior_bar_momentum, prior_bar_mean_reversion,
    atr_breakout, vwap_mean_reversion, opening_range_breakout,
    random_entry_matched_holding,
    ema_crossover_9_21, donchian_channel_20, bollinger_mean_reversion_20,
    BASELINES,
)
from .signals import (
    EligibilityParams, recompute_trade_eligibility, trade_eligibility_audit,
)
from .portfolio import (
    PortfolioResult, enforce_family_concurrency, portfolio_equity_curve,
    FAMILY_OF_SYMBOL,
)

__all__ = [
    "Trade", "EventEngine", "BacktestParams", "BacktestResult", "trades_to_dataframe",
    "fixed_tick_cost", "roll_spread_half_spread", "impact_cost", "ALL_COST_MODELS",
    "compute_metrics", "regime_breakdown", "deflated_sharpe", "pbo_score",
    "buy_and_hold_intraday", "prior_bar_momentum", "prior_bar_mean_reversion",
    "atr_breakout", "vwap_mean_reversion", "opening_range_breakout",
    "random_entry_matched_holding",
    "ema_crossover_9_21", "donchian_channel_20", "bollinger_mean_reversion_20",
    "BASELINES",
    "EligibilityParams", "recompute_trade_eligibility", "trade_eligibility_audit",
    "PortfolioResult", "enforce_family_concurrency", "portfolio_equity_curve",
    "FAMILY_OF_SYMBOL",
]
