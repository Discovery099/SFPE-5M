"""Event-driven backtest engine (spec §9).

Semantics:
  - Entry: next source bar's open, plus slippage.
  - Stop / target: simulated using the bar's high/low within the holding period.
  - Same-bar stop+target ambiguity: **conservative stop hit first** (spec §8.3).
  - Session-end policy: force flat at session end.
  - Family concurrency: at most one open trade per family (configurable).
  - Skip-after-roll: a flagged roll date is excluded for entries on the source bar
    immediately following it.
  - Sizing: per-trade risk = `risk_per_trade * equity / stop_distance_in_dollars`,
    rounded down to integer contracts (min 1).

This engine consumes:
  - source_df: per-source-bar DataFrame (must have timestamp, OHLCV, atr_20,
    session_date, plus regime, vpin, etc. if the strategy uses them).
  - signals_df: per-source-bar DataFrame with strategy outputs:
      bias (-1 / 0 / +1), confidence (0..1),
      projected_close_low / mid / high (target candidate), trade_eligible (bool),
      regime_label, vpin_gate, session_phase (optional, for breakdowns)
  - inst_cfg: instrument dict (point_value, tick_size, family, etc.)
  - cost_fn: function (entry_row, exit_row, contracts) -> dollar cost
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd


@dataclass
class Trade:
    symbol: str
    family: str
    entry_idx: int
    entry_time: pd.Timestamp
    entry_price: float
    direction: int                # +1 long / -1 short
    contracts: int
    stop_price: float
    target_price: float
    exit_idx: Optional[int] = None
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: str = "open"     # target / stop / session_end / time_stop / opposite_signal
    bars_held: int = 0
    gross_pnl: float = 0.0
    cost: float = 0.0
    net_pnl: float = 0.0
    mae: float = 0.0              # max adverse excursion (price units)
    mfe: float = 0.0              # max favorable excursion
    regime_at_entry: str = ""
    vpin_at_entry: str = ""
    session_phase_at_entry: str = ""
    session_date: object = None
    stress_at_entry: bool = False


@dataclass
class BacktestParams:
    starting_equity: float = 100_000.0
    risk_per_trade: float = 0.005          # 0.5% of equity per trade
    max_concurrent_positions: int = 3
    family_concurrency_limit: int = 1
    slippage_mult: float = 1.0             # 1x / 2x / 3x via this multiplier
    slippage_ticks: float = 1.0            # base entry+exit slippage in ticks
    stop_atr_mult: float = 1.0             # stop = entry +/- 1.0 * ATR_20 at entry
    target_atr_mult_min: float = 0.7       # target >= entry + 0.7 * ATR_20 (so R/R >=0.7)
    max_bars_hold: int = 20                # time-stop


@dataclass
class BacktestResult:
    symbol: str
    trades: list[Trade]
    equity_curve: pd.Series      # per-trade-close equity
    params: BacktestParams
    cost_model_name: str
    metrics: dict = field(default_factory=dict)


class EventEngine:
    """Sequential per-instrument backtest. Family concurrency is handled by the
    portfolio-level orchestrator (engine just emits trades and the runner enforces)."""

    def __init__(self, params: Optional[BacktestParams] = None):
        self.params = params or BacktestParams()

    def run(
        self,
        *,
        source_df: pd.DataFrame,
        signals_df: pd.DataFrame,
        inst_cfg: dict,
        cost_fn: Callable,
        cost_model_name: str = "fixed_tick",
        roll_skip_idxs: Optional[set[int]] = None,
    ) -> BacktestResult:
        p = self.params
        symbol = inst_cfg["symbol"]
        family = inst_cfg["family"]
        point_value = float(inst_cfg["point_value"])
        tick_size = float(inst_cfg["tick_size"])
        roll_skip_idxs = roll_skip_idxs or set()

        n = len(source_df)
        opens = source_df["open"].values
        highs = source_df["high"].values
        lows = source_df["low"].values
        closes = source_df["close"].values
        times = source_df["timestamp"].tolist()
        sds = source_df["session_date"].values
        atrs = source_df["atr_20"].values

        bias = signals_df["bias"].values if "bias" in signals_df else np.zeros(n)
        eligible = signals_df.get("trade_eligible", pd.Series([False] * n)).values
        regime_arr = signals_df.get("regime_label", pd.Series([""] * n)).astype(str).values
        vpin_arr = signals_df.get("vpin_gate", pd.Series([""] * n)).astype(str).values
        phase_arr = signals_df.get("session_phase", pd.Series([""] * n)).astype(str).values

        trades: list[Trade] = []
        equity = p.starting_equity
        equity_curve_idx: list[pd.Timestamp] = []
        equity_curve_val: list[float] = []

        open_trade: Optional[Trade] = None
        i = 0
        while i < n:
            sd_i = sds[i]
            is_session_end = (i == n - 1) or (sds[i + 1] != sd_i)

            if open_trade is not None:
                # Check session-end flatten (always exit at last bar of session).
                ot = open_trade
                hi_i, lo_i = highs[i], lows[i]
                # MAE / MFE update
                if ot.direction > 0:
                    excursion_adv = ot.entry_price - lo_i
                    excursion_fav = hi_i - ot.entry_price
                else:
                    excursion_adv = hi_i - ot.entry_price
                    excursion_fav = ot.entry_price - lo_i
                if excursion_adv > ot.mae:
                    ot.mae = float(excursion_adv)
                if excursion_fav > ot.mfe:
                    ot.mfe = float(excursion_fav)

                # Check stop/target. CONSERVATIVE: stop hit first on same bar.
                hit_stop = False
                hit_target = False
                if ot.direction > 0:
                    hit_stop = lo_i <= ot.stop_price
                    hit_target = hi_i >= ot.target_price
                    exit_price = ot.stop_price if hit_stop else (ot.target_price if hit_target else None)
                    exit_reason = "stop" if hit_stop else ("target" if hit_target else "open")
                else:
                    hit_stop = hi_i >= ot.stop_price
                    hit_target = lo_i <= ot.target_price
                    exit_price = ot.stop_price if hit_stop else (ot.target_price if hit_target else None)
                    exit_reason = "stop" if hit_stop else ("target" if hit_target else "open")

                ot.bars_held = i - ot.entry_idx
                time_stop = ot.bars_held >= p.max_bars_hold

                if hit_stop or hit_target or is_session_end or time_stop:
                    if exit_price is None:
                        exit_price = closes[i]
                        exit_reason = "session_end" if is_session_end else "time_stop"
                    # Apply slippage on exit (worsens fill).
                    slip = p.slippage_mult * p.slippage_ticks * tick_size
                    if ot.direction > 0:
                        fill_exit = exit_price - slip
                    else:
                        fill_exit = exit_price + slip
                    gross = (fill_exit - ot.entry_price) * ot.direction * point_value * ot.contracts
                    cost = cost_fn(
                        entry_row=dict(price=ot.entry_price,
                                       atr=atrs[ot.entry_idx],
                                       volume=source_df["volume"].iloc[ot.entry_idx],
                                       roll_spread=signals_df.get("roll_spread_proxy", pd.Series([0]*n)).iloc[ot.entry_idx] if "roll_spread_proxy" in signals_df else 0,
                                       price_return=closes[ot.entry_idx] - closes[max(ot.entry_idx-1, 0)]),
                        exit_row=dict(price=fill_exit),
                        contracts=ot.contracts,
                        tick_size=tick_size, tick_value=float(inst_cfg["tick_value"]),
                        point_value=point_value,
                    ) * p.slippage_mult
                    net = gross - cost
                    ot.exit_idx = i
                    ot.exit_time = times[i]
                    ot.exit_price = float(fill_exit)
                    ot.exit_reason = exit_reason
                    ot.gross_pnl = float(gross)
                    ot.cost = float(cost)
                    ot.net_pnl = float(net)
                    equity += net
                    equity_curve_idx.append(times[i])
                    equity_curve_val.append(equity)
                    open_trade = None

            # Entry logic (only if no open trade).
            if open_trade is None and eligible[i] and bias[i] != 0:
                # respect roll-skip: do not enter on bar immediately after a flagged roll date
                if (i - 1) in roll_skip_idxs or i in roll_skip_idxs:
                    i += 1
                    continue
                if i >= n - 1:  # no next-bar fill possible
                    break
                # Next-bar open fill (with slippage)
                slip = p.slippage_mult * p.slippage_ticks * tick_size
                direction = int(bias[i])
                fill = opens[i + 1] + (slip if direction > 0 else -slip)
                atr_e = atrs[i + 1]
                if not (atr_e and atr_e > 0):
                    i += 1
                    continue
                stop_dist = p.stop_atr_mult * atr_e
                target_dist = max(p.target_atr_mult_min * atr_e, stop_dist * 1.0)
                stop_price = fill - direction * stop_dist
                target_price = fill + direction * target_dist
                # Sizing: risk-based
                risk_dollars = p.risk_per_trade * equity
                stop_dollars = stop_dist * point_value
                contracts = max(1, int(risk_dollars // max(stop_dollars, 1e-6)))
                # Cap by max_concurrent in equity terms
                contracts = min(contracts, max(1, int(equity * 0.20 / max(fill * 0.05 * point_value, 1))))

                t = Trade(
                    symbol=symbol, family=family,
                    entry_idx=i + 1, entry_time=times[i + 1], entry_price=float(fill),
                    direction=direction, contracts=int(contracts),
                    stop_price=float(stop_price), target_price=float(target_price),
                    regime_at_entry=str(regime_arr[i]),
                    vpin_at_entry=str(vpin_arr[i]),
                    session_phase_at_entry=str(phase_arr[i]),
                    session_date=sds[i],
                )
                # stress window flag
                try:
                    sd_d = pd.Timestamp(sds[i]).date()
                except Exception:
                    sd_d = sds[i]
                STRESS = [(pd.Timestamp("2020-02-20").date(), pd.Timestamp("2020-05-31").date()),
                          (pd.Timestamp("2022-06-01").date(), pd.Timestamp("2022-10-31").date()),
                          (pd.Timestamp("2023-03-01").date(), pd.Timestamp("2023-05-31").date())]
                try:
                    t.stress_at_entry = any(s <= sd_d <= e for s, e in STRESS)
                except Exception:
                    t.stress_at_entry = False
                open_trade = t
                trades.append(t)
            i += 1

        # If a trade is still open at end of data, close at last close.
        if open_trade is not None and open_trade.exit_idx is None:
            ot = open_trade
            last = n - 1
            ot.exit_idx = last
            ot.exit_time = times[last]
            ot.exit_price = float(closes[last])
            ot.exit_reason = "end_of_data"
            ot.bars_held = last - ot.entry_idx
            gross = (closes[last] - ot.entry_price) * ot.direction * point_value * ot.contracts
            ot.gross_pnl = float(gross)
            ot.cost = 0.0
            ot.net_pnl = float(gross)
            equity += gross
            equity_curve_idx.append(times[last])
            equity_curve_val.append(equity)

        eq = pd.Series(equity_curve_val, index=equity_curve_idx, name="equity")
        return BacktestResult(
            symbol=symbol, trades=trades, equity_curve=eq, params=p,
            cost_model_name=cost_model_name,
        )


def trades_to_dataframe(trades: list[Trade]) -> pd.DataFrame:
    rows = []
    for t in trades:
        rows.append({
            "symbol": t.symbol, "family": t.family,
            "entry_idx": t.entry_idx, "entry_time": t.entry_time,
            "entry_price": t.entry_price, "direction": t.direction,
            "contracts": t.contracts, "stop_price": t.stop_price,
            "target_price": t.target_price,
            "exit_idx": t.exit_idx, "exit_time": t.exit_time,
            "exit_price": t.exit_price, "exit_reason": t.exit_reason,
            "bars_held": t.bars_held,
            "gross_pnl": t.gross_pnl, "cost": t.cost, "net_pnl": t.net_pnl,
            "mae": t.mae, "mfe": t.mfe,
            "regime_at_entry": t.regime_at_entry,
            "vpin_at_entry": t.vpin_at_entry,
            "session_phase_at_entry": t.session_phase_at_entry,
            "session_date": str(t.session_date),
            "stress_at_entry": t.stress_at_entry,
        })
    return pd.DataFrame(rows)
