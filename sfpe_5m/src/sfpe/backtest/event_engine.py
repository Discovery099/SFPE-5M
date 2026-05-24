"""Event-driven backtest engine (spec §9 + §8.3 projection-aware exits).

v1.5 semantics (Phase 5.5 upgrade, 2026-05-24):
  - Entry: next source bar's open, plus slippage.
  - Stop / target are projection-aware when `use_projection_exits=True`:
      * TP1 = projected_close_mid (50% partial exit; spec §8.3).
      * TP2 = projected_close_high (long) / projected_close_low (short).
      * Stop = structural_stop_long/short when has_structural_stop True
              (anchor ± buffer × ATR_20).
              Else fallback: synthetic_open_anchor ± fallback_buffer × ATR_20.
      * Time-stop = ceil(projected_completion_median × projection_hold_mult).
    When `use_projection_exits=False` (baselines) the engine uses the original
    generic ATR fallback (stop = ±stop_atr_mult × ATR_20; target = ±target_atr_mult_min × ATR_20).
  - Same-bar stop+target ambiguity: **conservative stop hit first** (spec §8.3).
  - Session-end policy: force flat at session end (closes BOTH partial leg and runner).
  - Family concurrency: at most one open trade per family (configurable; portfolio
    orchestrator enforces at portfolio level).
  - Skip-after-roll: a flagged roll date is excluded for entries on the source
    bar immediately following it.
  - Sizing: per-trade risk = `risk_per_trade * equity / stop_distance_in_dollars`,
    rounded down to integer contracts (min 1).
  - TP1 partial: triggered only when contracts ≥ 2 (cannot split 1 contract).

This engine consumes:
  - source_df: per-source-bar DataFrame (timestamp, OHLCV, atr_20, session_date).
  - signals_df: per-source-bar DataFrame with at minimum bias + trade_eligible.
       When `use_projection_exits=True` additionally requires
       projected_close_low/mid/high, projected_completion_median,
       structural_stop_long/short, has_structural_stop, synthetic_open_anchor.
  - inst_cfg: instrument dict (point_value, tick_size, tick_value, family).
  - cost_fn: (entry_row, exit_row, contracts) -> dollar cost.
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
    contracts: int                # initial contracts at entry
    stop_price: float
    target_price: float           # for projection-aware exits: this is TP2 (runner target)
    # v1.5 — projection-aware exit detail
    tp1_price: Optional[float] = None
    tp1_hit: bool = False
    tp1_idx: Optional[int] = None
    tp1_time: Optional[pd.Timestamp] = None
    tp1_fill_price: Optional[float] = None
    tp1_contracts: int = 0
    runner_contracts: int = 0
    use_projection_exits: bool = False
    exit_idx: Optional[int] = None
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None    # weighted-avg of TP1 + runner exits
    exit_reason: str = "open"             # tp1_only_tp2, tp2_runner, stop, stop_runner_after_tp1,
                                          # session_end, time_stop, etc.
    bars_held: int = 0
    gross_pnl: float = 0.0
    cost: float = 0.0
    net_pnl: float = 0.0
    mae: float = 0.0
    mfe: float = 0.0
    regime_at_entry: str = ""
    vpin_at_entry: str = ""
    session_phase_at_entry: str = ""
    session_date: object = None
    stress_at_entry: bool = False


@dataclass
class BacktestParams:
    starting_equity: float = 100_000.0
    risk_per_trade: float = 0.005
    max_concurrent_positions: int = 3
    family_concurrency_limit: int = 1
    slippage_mult: float = 1.0
    slippage_ticks: float = 1.0
    # Legacy ATR-based defaults (used when use_projection_exits=False)
    stop_atr_mult: float = 1.0
    target_atr_mult_min: float = 0.7
    max_bars_hold: int = 20
    # v1.5 — projection-aware exit knobs
    use_projection_exits: bool = False
    tp1_partial_fraction: float = 0.5      # fraction of contracts to exit at TP1
    fallback_buffer_atr_mult: float = 0.5  # synth_open ± mult × ATR for no-override stop
    projection_hold_mult: float = 1.5      # max_bars_hold = ceil(proj_completion_med × mult)
    # When projected completion median is NaN OR <1, fall back to this static.
    projection_hold_fallback: int = 12


@dataclass
class BacktestResult:
    symbol: str
    trades: list[Trade]
    equity_curve: pd.Series
    params: BacktestParams
    cost_model_name: str
    metrics: dict = field(default_factory=dict)


def _safe_int_ceil(x: float, fallback: int) -> int:
    if x is None or (isinstance(x, float) and (np.isnan(x) or x < 1.0)):
        return int(fallback)
    return int(np.ceil(x))


class EventEngine:
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
        if "roll_spread_proxy" in signals_df.columns:
            rsp_arr = signals_df["roll_spread_proxy"].fillna(0.0).astype(float).values
        else:
            rsp_arr = np.zeros(n, dtype=float)
        volumes = source_df["volume"].values
        prev_closes = np.r_[closes[0], closes[:-1]]
        price_returns = closes - prev_closes

        # v1.5 — projection-aware columns. When use_projection_exits is True we
        # require these to be present; otherwise they default to NaN/False and
        # the engine uses the legacy ATR-based path.
        def _col(name: str, default) -> np.ndarray:
            if name in signals_df.columns:
                return signals_df[name].astype(float).values
            return np.full(n, default, dtype=float)

        proj_close_low = _col("projected_close_low", np.nan)
        proj_close_mid = _col("projected_close_mid", np.nan)
        proj_close_high = _col("projected_close_high", np.nan)
        proj_completion_median = _col("projected_completion_median", np.nan)
        structural_stop_long = _col("structural_stop_long", np.nan)
        structural_stop_short = _col("structural_stop_short", np.nan)
        if "has_structural_stop" in signals_df.columns:
            has_struct = signals_df["has_structural_stop"].astype(bool).values
        else:
            has_struct = np.zeros(n, dtype=bool)
        synth_open_anchor = _col("synthetic_open_anchor", np.nan)

        trades: list[Trade] = []
        equity = p.starting_equity
        equity_curve_idx: list[pd.Timestamp] = []
        equity_curve_val: list[float] = []

        open_trade: Optional[Trade] = None
        # Per-trade dynamic state for projection-aware exits
        ot_max_hold: int = p.max_bars_hold

        i = 0
        while i < n:
            sd_i = sds[i]
            is_session_end = (i == n - 1) or (sds[i + 1] != sd_i)

            if open_trade is not None:
                ot = open_trade
                hi_i, lo_i = highs[i], lows[i]
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

                # Conservative stop-first ordering.
                # Compute hits on the runner-leg target (ot.target_price = TP2).
                # TP1 partial detection is only meaningful when an actual partial
                # leg was allocated at entry (tp1_contracts >= 1). If contracts == 1
                # we cannot split, so we DO NOT mark tp1_hit even if price touches TP1.
                if ot.direction > 0:
                    hit_stop = lo_i <= ot.stop_price
                    hit_tp2 = hi_i >= ot.target_price
                    hit_tp1 = (ot.use_projection_exits and not ot.tp1_hit
                                and ot.tp1_contracts >= 1
                                and ot.tp1_price is not None and hi_i >= ot.tp1_price)
                else:
                    hit_stop = hi_i >= ot.stop_price
                    hit_tp2 = lo_i <= ot.target_price
                    hit_tp1 = (ot.use_projection_exits and not ot.tp1_hit
                                and ot.tp1_contracts >= 1
                                and ot.tp1_price is not None and lo_i <= ot.tp1_price)

                ot.bars_held = i - ot.entry_idx
                time_stop = ot.bars_held >= ot_max_hold

                # TP1 partial-exit handling (BEFORE stop/TP2/session-end resolution).
                # On same bar, conservative rule: stop hit first if both touched.
                if hit_tp1 and not hit_stop:
                    # Realise the partial leg.
                    slip = p.slippage_mult * p.slippage_ticks * tick_size
                    if ot.direction > 0:
                        fill_tp1 = ot.tp1_price - slip
                    else:
                        fill_tp1 = ot.tp1_price + slip
                    ot.tp1_hit = True
                    ot.tp1_idx = i
                    ot.tp1_time = times[i]
                    ot.tp1_fill_price = float(fill_tp1)
                    # No reduction of `contracts` field — we report partial contracts
                    # via ot.tp1_contracts; the runner uses ot.runner_contracts.

                if (hit_stop or hit_tp2 or is_session_end or time_stop):
                    # Determine runner exit price and reason.
                    if hit_stop:
                        exit_price_runner = ot.stop_price
                        exit_reason = "stop"
                    elif hit_tp2:
                        exit_price_runner = ot.target_price
                        exit_reason = "tp2" if ot.use_projection_exits else "target"
                    elif is_session_end:
                        exit_price_runner = closes[i]
                        exit_reason = "session_end"
                    else:
                        exit_price_runner = closes[i]
                        exit_reason = "time_stop"
                    # Slippage on runner exit.
                    slip = p.slippage_mult * p.slippage_ticks * tick_size
                    if ot.direction > 0:
                        fill_runner = exit_price_runner - slip
                    else:
                        fill_runner = exit_price_runner + slip

                    # Compute PnL for the runner leg.
                    runner_contracts = ot.runner_contracts if ot.tp1_hit else ot.contracts
                    tp1_contracts = ot.tp1_contracts if ot.tp1_hit else 0
                    # If partial leg was filled, include that PnL.
                    if ot.tp1_hit and ot.tp1_fill_price is not None and tp1_contracts > 0:
                        tp1_gross = (ot.tp1_fill_price - ot.entry_price) * ot.direction * point_value * tp1_contracts
                    else:
                        tp1_gross = 0.0
                    runner_gross = (fill_runner - ot.entry_price) * ot.direction * point_value * runner_contracts
                    gross = tp1_gross + runner_gross

                    # Compose exit_reason describing the full disposition.
                    if ot.tp1_hit:
                        if hit_stop:
                            exit_reason = "stop_after_tp1"
                        elif hit_tp2:
                            exit_reason = "tp2_after_tp1"
                        elif is_session_end:
                            exit_reason = "session_end_after_tp1"
                        elif time_stop:
                            exit_reason = "time_stop_after_tp1"

                    # Cost: one entry+exit pair on partial (if filled) + one on runner.
                    # The cost_fn returns USD per entry-exit roundtrip for `contracts`
                    # contracts.  Apply once on the total notional roundtrip.
                    total_round_trips = (tp1_contracts if ot.tp1_hit else 0) + runner_contracts
                    cost = cost_fn(
                        entry_row=dict(price=ot.entry_price,
                                       atr=atrs[ot.entry_idx],
                                       volume=volumes[ot.entry_idx],
                                       roll_spread=rsp_arr[ot.entry_idx],
                                       price_return=price_returns[ot.entry_idx]),
                        exit_row=dict(price=fill_runner),
                        contracts=max(1, int(total_round_trips)),
                        tick_size=tick_size, tick_value=float(inst_cfg["tick_value"]),
                        point_value=point_value,
                    ) * p.slippage_mult
                    net = gross - cost
                    ot.exit_idx = i
                    ot.exit_time = times[i]
                    # Weighted-avg exit price for downstream tooling.
                    if ot.tp1_hit and tp1_contracts > 0 and runner_contracts > 0:
                        ot.exit_price = float(
                            (ot.tp1_fill_price * tp1_contracts +
                             fill_runner * runner_contracts) /
                            (tp1_contracts + runner_contracts)
                        )
                    else:
                        ot.exit_price = float(fill_runner)
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
                if (i - 1) in roll_skip_idxs or i in roll_skip_idxs:
                    i += 1
                    continue
                if i >= n - 1:
                    break
                slip = p.slippage_mult * p.slippage_ticks * tick_size
                direction = int(bias[i])
                fill = opens[i + 1] + (slip if direction > 0 else -slip)
                atr_e = atrs[i + 1]
                if not (atr_e and atr_e > 0):
                    i += 1
                    continue

                if p.use_projection_exits:
                    # ---- Projection-aware exit construction (spec §8.3) ----
                    tp1 = proj_close_mid[i]
                    tp2 = proj_close_high[i] if direction > 0 else proj_close_low[i]
                    # Skip if projection envelope is degenerate or wrong-sided.
                    if not (np.isfinite(tp1) and np.isfinite(tp2)):
                        i += 1
                        continue
                    if direction > 0 and not (tp1 > fill and tp2 >= tp1):
                        # Projection mid is below entry, or TP2 below TP1 — degenerate.
                        i += 1
                        continue
                    if direction < 0 and not (tp1 < fill and tp2 <= tp1):
                        i += 1
                        continue
                    # Stop: structural override if present + finite + on correct side.
                    # Per-direction gate: a LONG trade only needs structural_stop_long
                    # to be finite, etc.
                    side_stop = structural_stop_long[i] if direction > 0 else structural_stop_short[i]
                    if has_struct[i] and np.isfinite(side_stop):
                        stop_price = side_stop
                        # Guard: stop must be on the correct side of the entry.
                        if (direction > 0 and stop_price >= fill) or (direction < 0 and stop_price <= fill):
                            # Structural anchor invalid for this entry — fall back.
                            synth_open = synth_open_anchor[i] if np.isfinite(synth_open_anchor[i]) else fill
                            buf = p.fallback_buffer_atr_mult * atr_e
                            stop_price = synth_open - direction * buf
                    else:
                        synth_open = synth_open_anchor[i] if np.isfinite(synth_open_anchor[i]) else fill
                        buf = p.fallback_buffer_atr_mult * atr_e
                        stop_price = synth_open - direction * buf
                    # Final guard: stop must be on the correct side & nontrivial distance.
                    stop_dist = abs(fill - stop_price)
                    if stop_dist < 0.5 * tick_size:
                        i += 1
                        continue
                    target_price = float(tp2)
                    # Time-stop per spec §8.3: ceil(proj_completion_median × mult).
                    ot_max_hold = _safe_int_ceil(
                        proj_completion_median[i] * p.projection_hold_mult,
                        fallback=p.projection_hold_fallback,
                    )
                else:
                    # ---- Legacy ATR-based fallback (baselines) ----
                    stop_dist = p.stop_atr_mult * atr_e
                    target_dist = max(p.target_atr_mult_min * atr_e, stop_dist * 1.0)
                    stop_price = fill - direction * stop_dist
                    target_price = fill + direction * target_dist
                    tp1 = np.nan
                    ot_max_hold = p.max_bars_hold

                # Sizing: risk-based.
                risk_dollars = p.risk_per_trade * equity
                stop_dollars = stop_dist * point_value
                contracts = max(1, int(risk_dollars // max(stop_dollars, 1e-6)))
                contracts = min(contracts, max(1, int(equity * 0.20 / max(fill * 0.05 * point_value, 1))))

                # TP1 partial allocation (only if contracts >= 2 and projection exits enabled).
                if p.use_projection_exits and contracts >= 2:
                    tp1_contracts = int(round(contracts * p.tp1_partial_fraction))
                    tp1_contracts = max(1, min(tp1_contracts, contracts - 1))
                    runner_contracts = contracts - tp1_contracts
                else:
                    tp1_contracts = 0
                    runner_contracts = contracts

                t = Trade(
                    symbol=symbol, family=family,
                    entry_idx=i + 1, entry_time=times[i + 1], entry_price=float(fill),
                    direction=direction, contracts=int(contracts),
                    stop_price=float(stop_price), target_price=float(target_price),
                    tp1_price=float(tp1) if np.isfinite(tp1) else None,
                    tp1_contracts=int(tp1_contracts),
                    runner_contracts=int(runner_contracts),
                    use_projection_exits=bool(p.use_projection_exits),
                    regime_at_entry=str(regime_arr[i]),
                    vpin_at_entry=str(vpin_arr[i]),
                    session_phase_at_entry=str(phase_arr[i]),
                    session_date=sds[i],
                )
                try:
                    sd_d = pd.Timestamp(sds[i]).date()
                except Exception:
                    sd_d = sds[i]
                STRESS = [(pd.Timestamp("2020-02-20").date(), pd.Timestamp("2020-05-31").date()),
                          (pd.Timestamp("2022-06-01").date(), pd.Timestamp("2022-10-31").date()),
                          (pd.Timestamp("2023-03-01").date(), pd.Timestamp("2023-09-30").date())]
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
            tp1_contracts = ot.tp1_contracts if ot.tp1_hit else 0
            runner_contracts = ot.runner_contracts if ot.tp1_hit else ot.contracts
            if ot.tp1_hit and ot.tp1_fill_price is not None and tp1_contracts > 0:
                tp1_gross = (ot.tp1_fill_price - ot.entry_price) * ot.direction * point_value * tp1_contracts
            else:
                tp1_gross = 0.0
            runner_gross = (closes[last] - ot.entry_price) * ot.direction * point_value * runner_contracts
            ot.gross_pnl = float(tp1_gross + runner_gross)
            ot.cost = 0.0
            ot.net_pnl = float(ot.gross_pnl)
            equity += ot.net_pnl
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
            "tp1_price": t.tp1_price, "tp1_hit": t.tp1_hit,
            "tp1_fill_price": t.tp1_fill_price,
            "tp1_contracts": t.tp1_contracts, "runner_contracts": t.runner_contracts,
            "use_projection_exits": t.use_projection_exits,
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
