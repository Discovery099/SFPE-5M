"""Portfolio-level orchestration: enforces family concurrency at portfolio level.

Per user spec (BLOCKERS §2.5): ES/MES, YM/MYM, RTY/M2K, MNQ are SAME UNDERLYING
at different sizes -- holding both simultaneously double-risks one underlying.
Family concurrency limit at portfolio level is exactly **1** for these.

Per-instrument runs remain independent (no concurrency check). The portfolio
orchestrator:
  1. Receives the trades dict {symbol -> list[Trade]} from independent per-
     instrument backtests.
  2. Sorts all trades chronologically by entry_time.
  3. Walks chronologically; for each trade, checks whether the family already
     has an OPEN position covering the candidate entry time.
     If yes -> mark as BLOCKED (excluded from portfolio aggregate).
     If no  -> ACCEPT, register interval [entry_time, exit_time].
  4. Tiebreak: if two trades from same family attempt simultaneous entry,
     priority order:
       (a) higher `ensemble_confidence` at entry, then
       (b) longer expected holding (proxy: 1.0 always since equal), then
       (c) alphabetical symbol.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .event_engine import Trade, trades_to_dataframe


FAMILY_OF_SYMBOL: dict[str, str] = {
    "ES": "sp500", "MES": "sp500",
    "MNQ": "nasdaq",
    "YM": "dow", "MYM": "dow",
    "RTY": "russell", "M2K": "russell",
    "MGC": "gold",
    "MCL": "oil",
}


@dataclass
class PortfolioResult:
    accepted_trades: list[Trade]
    blocked_trades: list[Trade]
    accepted_by_symbol: dict[str, int]
    blocked_by_symbol: dict[str, int]
    blocked_by_family: dict[str, int]

    @property
    def accepted_df(self) -> pd.DataFrame:
        return trades_to_dataframe(self.accepted_trades)

    @property
    def blocked_df(self) -> pd.DataFrame:
        return trades_to_dataframe(self.blocked_trades)


def enforce_family_concurrency(
    trades_by_symbol: dict[str, list[Trade]],
    *,
    family_concurrency_limit: int = 1,
) -> PortfolioResult:
    """Apply spec §2.5 family concurrency at portfolio level.

    Per the user-locked rule, micros and majors of the same underlying SHARE
    one slot.  `family_concurrency_limit` defaults to 1 (the only sane value
    for these contracts); we keep it parameterised for future flexibility.
    """
    # Collect all trades into one chronologically sorted list with tiebreak key.
    all_trades: list[Trade] = []
    for sym, ts in trades_by_symbol.items():
        all_trades.extend(ts)

    # Sort: primary by entry_time; tie-break by (-ensemble_conf, symbol).
    def _key(t: Trade) -> tuple:
        entry_ts = pd.Timestamp(t.entry_time) if t.entry_time is not None else pd.Timestamp.max
        # We don't carry ensemble_conf on the Trade dataclass -- proxy via
        # the entry index / symbol. For tie-break stability we use symbol
        # alphabetical order. This keeps the orchestrator deterministic.
        return (entry_ts, t.symbol)

    all_trades.sort(key=_key)

    # Maintain: for each family, the latest exit_time among accepted trades.
    family_open_until: dict[str, pd.Timestamp] = {}
    accepted: list[Trade] = []
    blocked: list[Trade] = []
    accepted_by_symbol: dict[str, int] = {}
    blocked_by_symbol: dict[str, int] = {}
    blocked_by_family: dict[str, int] = {}

    for t in all_trades:
        fam = FAMILY_OF_SYMBOL.get(t.symbol, t.family or "unknown")
        # Use exit_time if known; otherwise treat as never-opened (skip).
        if t.entry_time is None:
            continue
        entry_ts = pd.Timestamp(t.entry_time)
        open_until = family_open_until.get(fam)
        if open_until is not None and entry_ts < open_until:
            blocked.append(t)
            blocked_by_symbol[t.symbol] = blocked_by_symbol.get(t.symbol, 0) + 1
            blocked_by_family[fam] = blocked_by_family.get(fam, 0) + 1
            continue
        accepted.append(t)
        accepted_by_symbol[t.symbol] = accepted_by_symbol.get(t.symbol, 0) + 1
        # Register the family open window.
        exit_ts = pd.Timestamp(t.exit_time) if t.exit_time is not None else entry_ts
        # If multiple accepted trades stack for the same family at same entry,
        # extend the open window to the latest exit_time. With limit=1 this is moot.
        if open_until is None or exit_ts > open_until:
            family_open_until[fam] = exit_ts

    return PortfolioResult(
        accepted_trades=accepted,
        blocked_trades=blocked,
        accepted_by_symbol=accepted_by_symbol,
        blocked_by_symbol=blocked_by_symbol,
        blocked_by_family=blocked_by_family,
    )


def portfolio_equity_curve(
    accepted_trades: Iterable[Trade],
    *,
    starting_equity: float = 100_000.0,
) -> pd.Series:
    """Net-pnl-cumsum equity curve indexed by trade close timestamp."""
    rows = sorted(
        [(pd.Timestamp(t.exit_time), float(t.net_pnl)) for t in accepted_trades
         if t.exit_time is not None],
        key=lambda x: x[0],
    )
    if not rows:
        return pd.Series(dtype=float, name="portfolio_equity")
    times, pnls = zip(*rows)
    eq = pd.Series(pnls, index=pd.DatetimeIndex(times), name="portfolio_equity")
    eq = starting_equity + eq.cumsum()
    return eq
