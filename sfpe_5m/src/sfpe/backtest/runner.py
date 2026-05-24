"""Phase 5 backtest runner — orchestration helpers used by `scripts/run_backtest.py`.

Top-level flow per instrument:
  1. Load source bars via the production loader (tz-aware in America/New_York).
  2. Recompute trade_eligibility from the ensemble CSV (BLOCKERS §38 fix).
  3. Map v1.4 flagged roll dates (from `reports/v1_4_roll_candidates.csv`) to
     source-bar row indices for `roll_skip_idxs`.
  4. Run EventEngine for the strategy at each (cost_model × slippage × threshold)
     variant.
  5. Run all 10 baselines (under realistic cost + 1× slippage only — fair).
  6. Return a dict of {variant_name: BacktestResult} suitable for aggregation.

The orchestrator at the portfolio level applies family-concurrency.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd
import yaml
from loguru import logger

from sfpe.data.calendar import load_calendars
from sfpe.data.loader import load_instrument_csv
from sfpe.backtest import (
    BASELINES,
    EligibilityParams,
    EventEngine,
    BacktestParams,
    BacktestResult,
    recompute_trade_eligibility,
    fixed_tick_cost,
    roll_spread_half_spread,
    impact_cost,
    trades_to_dataframe,
)
from sfpe.backtest.signals import StructuralStopParams


COST_FUNCS = {
    "fixed_tick":  fixed_tick_cost,
    "roll_spread": roll_spread_half_spread,
    "impact":      impact_cost,
}


@dataclass
class StrategyVariant:
    name: str
    cost_model: str
    slippage_mult: float
    min_confidence: float


def default_variants() -> list[StrategyVariant]:
    """Per user-locked spec (2026-05-24):
      - Primary cost model: `fixed_tick` (realistic CME exchange+clearing+NFA + 1 tick).
        Run at 1×/2×/3× slippage per spec §9.2.
      - Secondary cost models for comparison (1× slippage only):
          `roll_spread` (spec §9.2 microstructure proxy)
          `impact`      (price-impact proxy)
      - Two confidence thresholds: 0.50 and 0.65 (calibration sanity check).
    Total: (3 + 1 + 1) × 2 thresholds = 10 strategy variants per instrument.
    """
    out: list[StrategyVariant] = []
    # Primary: fixed_tick × 3 slippages.
    for sm in (1.0, 2.0, 3.0):
        for thr in (0.50, 0.65):
            out.append(StrategyVariant(
                name=f"strategy__cost=fixed_tick__slip={sm:.0f}x__conf={thr:.2f}",
                cost_model="fixed_tick", slippage_mult=sm, min_confidence=thr,
            ))
    # Secondary cost models: 1× slippage only (one comparison run per user spec).
    for cm in ("roll_spread", "impact"):
        for thr in (0.50, 0.65):
            out.append(StrategyVariant(
                name=f"strategy__cost={cm}__slip=1x__conf={thr:.2f}",
                cost_model=cm, slippage_mult=1.0, min_confidence=thr,
            ))
    return out


def build_roll_skip_idxs(
    *, source_df: pd.DataFrame, roll_candidates_csv: Path, symbol: str,
    mode: str = "v1_4",
) -> tuple[set[int], int]:
    """Translate roll-flagged date_next values for `symbol` to source-bar indices.

    A flagged roll date means: skip the source bar immediately AFTER that date
    (i.e. the first bar of the date_next session).
    Returns (set of row indices to skip for ENTRY, count of distinct flag dates).
    """
    if not roll_candidates_csv.exists():
        logger.warning(f"roll candidates CSV not found at {roll_candidates_csv}; "
                       f"no roll-skip will be applied for {symbol}")
        return set(), 0
    rc = pd.read_csv(roll_candidates_csv)
    rc = rc[(rc["mode"] == mode)]
    # The dataset symbol in the rolls CSV may be like "ES.v.0" while the
    # instruments.yaml symbol is "ES". Match the dataset symbol's PREFIX.
    rc["sym_short"] = rc["symbol"].astype(str).str.split(".").str[0]
    rc = rc[rc["sym_short"] == symbol]
    flagged_dates: set[pd.Timestamp] = set()
    for d in rc["date_next"].dropna():
        flagged_dates.add(pd.to_datetime(d).date())
    if not flagged_dates:
        return set(), 0
    # For each flagged date, find ALL source bar indices in that session and
    # skip them all (most conservative interpretation).
    sd_series = pd.to_datetime(source_df["session_date"]).dt.date
    mask = sd_series.isin(flagged_dates)
    idxs = set(np.flatnonzero(mask.values).tolist())
    # Also explicitly skip the FIRST bar of the next session per spec.
    # (already covered if the next session itself is a flagged session_date,
    #  but here we ensure the bar immediately following the flagged-date last
    #  bar is also excluded.)
    return idxs, len(flagged_dates)


def run_strategy_one_variant(
    *,
    source_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    inst_cfg: dict,
    variant: StrategyVariant,
    roll_skip_idxs: set[int],
    base_params: BacktestParams,
) -> BacktestResult:
    p = BacktestParams(
        starting_equity=base_params.starting_equity,
        risk_per_trade=base_params.risk_per_trade,
        max_concurrent_positions=base_params.max_concurrent_positions,
        family_concurrency_limit=base_params.family_concurrency_limit,
        slippage_mult=variant.slippage_mult,
        slippage_ticks=base_params.slippage_ticks,
        stop_atr_mult=base_params.stop_atr_mult,
        target_atr_mult_min=base_params.target_atr_mult_min,
        max_bars_hold=base_params.max_bars_hold,
        # v1.5: strategy ALWAYS uses projection-aware exits (spec §8.3).
        use_projection_exits=True,
        tp1_partial_fraction=base_params.tp1_partial_fraction,
        fallback_buffer_atr_mult=base_params.fallback_buffer_atr_mult,
        projection_hold_mult=base_params.projection_hold_mult,
        projection_hold_fallback=base_params.projection_hold_fallback,
    )
    engine = EventEngine(p)
    res = engine.run(
        source_df=source_df,
        signals_df=signals_df,
        inst_cfg=inst_cfg,
        cost_fn=COST_FUNCS[variant.cost_model],
        cost_model_name=variant.cost_model,
        roll_skip_idxs=roll_skip_idxs,
    )
    return res


def run_baseline_one(
    *,
    source_df: pd.DataFrame,
    name: str,
    inst_cfg: dict,
    roll_skip_idxs: set[int],
    base_params: BacktestParams,
) -> BacktestResult:
    """Run one baseline under the realistic cost model + 1× slippage.

    Baselines do NOT have a projection layer, so they keep the legacy
    ATR-based stop/target exits.  This is the FAIR comparison: strategy
    uses projection-derived exits, baselines use generic ATR exits.
    """
    fn = BASELINES[name]
    signals = fn(source_df)
    # Baselines do not gate by VPIN / regime / structural features.
    signals = signals.copy()
    signals["roll_spread_proxy"] = 0.0
    p = BacktestParams(
        starting_equity=base_params.starting_equity,
        risk_per_trade=base_params.risk_per_trade,
        max_concurrent_positions=base_params.max_concurrent_positions,
        family_concurrency_limit=base_params.family_concurrency_limit,
        slippage_mult=1.0,
        slippage_ticks=base_params.slippage_ticks,
        stop_atr_mult=base_params.stop_atr_mult,
        target_atr_mult_min=base_params.target_atr_mult_min,
        max_bars_hold=base_params.max_bars_hold,
        # Baselines NEVER use projection exits.
        use_projection_exits=False,
    )
    engine = EventEngine(p)
    res = engine.run(
        source_df=source_df,
        signals_df=signals,
        inst_cfg=inst_cfg,
        cost_fn=fixed_tick_cost,
        cost_model_name="fixed_tick",
        roll_skip_idxs=roll_skip_idxs,
    )
    res.symbol = f"{inst_cfg['symbol']}__baseline={name}"
    return res


def run_one_instrument(
    *,
    symbol: str,
    repo: Path,
    base_params: Optional[BacktestParams] = None,
    variants: Optional[list[StrategyVariant]] = None,
    run_strategy: bool = True,
    run_baselines: bool = True,
) -> dict:
    """Run all configured variants for one instrument.

    Returns {
       'symbol': str,
       'strategy_results': {variant_name: BacktestResult},
       'baseline_results':  {baseline_name: BacktestResult},
       'roll_skip_bar_count': int,
       'flagged_roll_date_count': int,
       'roll_skip_blocked_signal_count': int,    # would-be entries blocked
       'n_bars': int,
       'n_eligible_at_thresholds': {0.50: int, 0.65: int},
    }
    """
    bp = base_params or BacktestParams()
    variants = variants or default_variants()

    instruments_yaml = repo / "config" / "instruments.yaml"
    calendars_yaml = repo / "config" / "session_calendars.yaml"
    cfg = yaml.safe_load(instruments_yaml.read_text())
    cals = load_calendars(calendars_yaml)
    ic = cfg["instruments"][symbol]
    cal = cals[ic["calendar"]]

    logger.info(f"[{symbol}] loading source from {ic['file']}")
    source_df = load_instrument_csv(repo / ic["file"], cal)
    n_bars = len(source_df)

    ensemble_csv = repo / "features" / f"projection_ensemble__{symbol}.csv"
    regime_csv = repo / "features" / f"regime__{symbol}.csv"
    # v1.5 — structural-stop feature CSVs for spec §8.3 projection-aware exits.
    absorption_csv = repo / "features" / f"absorption__{symbol}.csv"
    vacuum_csv = repo / "features" / f"vacuum__{symbol}.csv"
    tpo_csv = repo / "features" / f"tpo__{symbol}.csv"
    stop_sp = StructuralStopParams(
        structural_buffer_atr_mult=0.5,
        fallback_buffer_atr_mult=0.5,
    )

    # Roll skip indices.
    roll_candidates_csv = repo / "reports" / "v1_4_roll_candidates.csv"
    roll_skip_idxs, n_flagged_dates = build_roll_skip_idxs(
        source_df=source_df, roll_candidates_csv=roll_candidates_csv,
        symbol=symbol, mode="v1_4",
    )
    logger.info(f"[{symbol}] roll-skip: {len(roll_skip_idxs):,} bars across "
                f"{n_flagged_dates} flagged dates")

    # Count how many would-be eligible signals fall on roll-skip bars (per user).
    blocked_count_by_thr: dict[float, int] = {}
    eligible_count_by_thr: dict[float, int] = {}
    for thr in (0.50, 0.65):
        sig = recompute_trade_eligibility(
            ensemble_csv=ensemble_csv, source_df=source_df, regime_csv=regime_csv,
            absorption_csv=absorption_csv, vacuum_csv=vacuum_csv, tpo_csv=tpo_csv,
            params=EligibilityParams(latest_entry_time_et=ic["latest_entry_time"],
                                       min_confidence=thr),
            structural_stop_params=stop_sp,
        )
        elig_idxs = np.flatnonzero(sig["trade_eligible"].values)
        blocked_count_by_thr[thr] = int(
            sum(1 for i in elig_idxs if (i in roll_skip_idxs or (i + 1) in roll_skip_idxs))
        )
        eligible_count_by_thr[thr] = int(sig["trade_eligible"].sum())

    out: dict = {
        "symbol": symbol,
        "n_bars": n_bars,
        "flagged_roll_date_count": int(n_flagged_dates),
        "roll_skip_bar_count": len(roll_skip_idxs),
        "roll_skip_blocked_signal_count": blocked_count_by_thr,
        "n_eligible_at_thresholds": eligible_count_by_thr,
        "strategy_results": {},
        "baseline_results": {},
    }
    inst_cfg_engine = dict(
        symbol=symbol, family=ic["family"],
        point_value=float(ic["point_value"]),
        tick_size=float(ic["tick_size"]),
        tick_value=float(ic["tick_value"]),
    )

    # Strategy runs.
    if run_strategy:
        # Build per-threshold signal frames ONCE (was recomputed per variant — perf bug).
        sigs_by_thr: dict[float, pd.DataFrame] = {}
        for thr in {v.min_confidence for v in variants}:
            sigs_by_thr[thr] = recompute_trade_eligibility(
                ensemble_csv=ensemble_csv, source_df=source_df, regime_csv=regime_csv,
                absorption_csv=absorption_csv, vacuum_csv=vacuum_csv, tpo_csv=tpo_csv,
                params=EligibilityParams(latest_entry_time_et=ic["latest_entry_time"],
                                           min_confidence=thr),
                structural_stop_params=stop_sp,
            )
        for v in variants:
            sig = sigs_by_thr[v.min_confidence]
            res = run_strategy_one_variant(
                source_df=source_df, signals_df=sig, inst_cfg=inst_cfg_engine,
                variant=v, roll_skip_idxs=roll_skip_idxs, base_params=bp,
            )
            out["strategy_results"][v.name] = res
            n_t = len(res.trades)
            n_tp1 = sum(1 for t in res.trades if t.tp1_hit)
            logger.info(f"[{symbol}] {v.name}  -> {n_t} trades  ({n_tp1} hit TP1)")

    # Baseline runs (realistic cost, 1× slippage).
    if run_baselines:
        for bname in BASELINES.keys():
            res = run_baseline_one(
                source_df=source_df, name=bname, inst_cfg=inst_cfg_engine,
                roll_skip_idxs=roll_skip_idxs, base_params=bp,
            )
            out["baseline_results"][bname] = res
            n_t = len(res.trades)
            logger.info(f"[{symbol}] baseline {bname:32s} -> {n_t} trades")

    return out
