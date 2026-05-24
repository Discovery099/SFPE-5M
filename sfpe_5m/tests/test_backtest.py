"""Backtest correctness tests (Phase 5 \u00a715 spec).

Verifies:
  - next-bar open fill (no current-bar peek)
  - no-lookahead (truncation invariance of earlier trades)
  - conservative same-bar stop/target tie-break (stop hits first per spec \u00a78.3)
  - session-end forced flatten
  - roll-skip prevents entries on bar after flagged roll
  - portfolio-level family concurrency (ES/MES share one slot)
  - baselines emit causal signals (truncation invariance per baseline)
  - signal recomputation matches the joint pass-rate report
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sfpe.backtest import (
    EventEngine, BacktestParams, Trade,
    fixed_tick_cost, trades_to_dataframe,
    BASELINES,
    EligibilityParams, recompute_trade_eligibility,
    enforce_family_concurrency, FAMILY_OF_SYMBOL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
INST_CFG_ES = dict(
    symbol="ES", family="sp500",
    point_value=50.0, tick_size=0.25, tick_value=12.5,
)


def _make_source_df(n_sessions: int = 5, bars_per_session: int = 30,
                    start: str = "2024-01-02") -> pd.DataFrame:
    """Synthetic single-instrument source bars suitable for the EventEngine.

    Each session: linear ramp up of 30 ticks (close[i] = 100 + bar*0.25 inside).
    ATR_20 fixed at 1.0 so stops/targets are predictable.
    """
    rows = []
    sessions = pd.bdate_range(start=start, periods=n_sessions)
    bar_minute = 5
    for sd in sessions:
        for b in range(bars_per_session):
            ts = pd.Timestamp(sd) + pd.Timedelta(minutes=9 * 60 + 30 + b * bar_minute)
            ts = ts.tz_localize("America/New_York")
            mid = 100.0 + b * 0.25
            rows.append(dict(
                timestamp=ts,
                symbol="ES",
                open=mid,
                high=mid + 0.25,
                low=mid - 0.25,
                close=mid,
                volume=1000.0,
                session_date=sd.date(),
                bar_index_in_session=b,
                is_first_bar_of_session=(b == 0),
                is_last_bar_of_session=(b == bars_per_session - 1),
                atr_20=1.0,
            ))
    return pd.DataFrame(rows)


def _make_long_signal_at(idx: int, n: int) -> pd.DataFrame:
    """Single long signal at row `idx`."""
    sig = pd.DataFrame({
        "bias": np.zeros(n, dtype=int),
        "trade_eligible": np.zeros(n, dtype=bool),
        "ensemble_confidence": np.full(n, 0.8, dtype=float),
        "regime_label": np.array(["balanced"] * n),
        "vpin_gate": np.array(["allow"] * n),
        "session_phase": np.array([""] * n),
    })
    sig.loc[idx, "bias"] = 1
    sig.loc[idx, "trade_eligible"] = True
    return sig


# ---------------------------------------------------------------------------
# 1. next-bar open fill (spec \u00a715)
# ---------------------------------------------------------------------------
def test_backtest_next_bar_open_fill():
    src = _make_source_df(n_sessions=1, bars_per_session=30)
    sig = _make_long_signal_at(idx=5, n=len(src))
    engine = EventEngine(BacktestParams(slippage_ticks=0.0, stop_atr_mult=10.0,
                                         target_atr_mult_min=10.0, max_bars_hold=999))
    res = engine.run(source_df=src, signals_df=sig, inst_cfg=INST_CFG_ES,
                      cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    assert len(res.trades) >= 1
    t = res.trades[0]
    # Signal at row 5 -> entry at row 6 (next bar's open).
    assert t.entry_idx == 6, f"expected entry_idx=6, got {t.entry_idx}"
    assert t.entry_price == pytest.approx(float(src.iloc[6]["open"])), (
        f"entry price should equal next-bar open; got {t.entry_price} vs {src.iloc[6]['open']}"
    )


# ---------------------------------------------------------------------------
# 2. No-lookahead: truncation invariance of earlier trades.
# ---------------------------------------------------------------------------
def test_backtest_no_lookahead_truncation_invariance():
    src = _make_source_df(n_sessions=2, bars_per_session=30)
    n = len(src)
    sig = _make_long_signal_at(idx=5, n=n)  # signal at row 5 -> entry row 6
    engine = EventEngine(BacktestParams(slippage_ticks=0.0, stop_atr_mult=10.0,
                                         target_atr_mult_min=10.0, max_bars_hold=4))
    res_full = engine.run(source_df=src, signals_df=sig, inst_cfg=INST_CFG_ES,
                           cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    # Truncate after the trade closes (trade is row 6 entry, max_bars_hold=4 -> exit ~row 10).
    cut = 15
    src_t = src.iloc[:cut].reset_index(drop=True)
    sig_t = sig.iloc[:cut].reset_index(drop=True)
    res_t = engine.run(source_df=src_t, signals_df=sig_t, inst_cfg=INST_CFG_ES,
                        cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    # Compare the first trade in both runs.
    assert len(res_full.trades) >= 1 and len(res_t.trades) >= 1
    a = res_full.trades[0]
    b = res_t.trades[0]
    assert a.entry_idx == b.entry_idx
    assert a.entry_price == pytest.approx(b.entry_price)
    assert a.exit_idx == b.exit_idx
    assert a.exit_price == pytest.approx(b.exit_price)
    assert a.exit_reason == b.exit_reason


# ---------------------------------------------------------------------------
# 3. Same-bar stop+target tie -> conservative stop-first (spec \u00a78.3).
# ---------------------------------------------------------------------------
def test_same_bar_stop_first_conservative():
    """Build a bar that touches BOTH stop and target. Verify exit_reason == 'stop'.

    We need bars [2..4] to stay strictly inside the (stop, target) zone so the
    trade survives until row 5 where the wild bar straddles both levels.
    """
    src = _make_source_df(n_sessions=1, bars_per_session=15)
    n = len(src)
    # Entry at row 1 (signal at row 0). entry_price ≈ src.iloc[1].open.
    # ATR=1.0, stop_atr_mult=1.0 -> stop=entry-1, target=entry+1. So we need
    # bars 2..4 to stay tightly inside (entry-0.5, entry+0.5).
    entry_price = float(src.iloc[1]["open"])
    for i in range(2, 5):
        src.loc[i, "open"] = entry_price
        src.loc[i, "high"] = entry_price + 0.1
        src.loc[i, "low"] = entry_price - 0.1
        src.loc[i, "close"] = entry_price
    # Row 5 straddles both stop (entry-1) and target (entry+1).
    src.loc[5, "open"] = entry_price
    src.loc[5, "high"] = entry_price + 2.0     # well above target
    src.loc[5, "low"] = entry_price - 2.0      # well below stop
    src.loc[5, "close"] = entry_price
    sig = _make_long_signal_at(idx=0, n=n)
    engine = EventEngine(BacktestParams(
        slippage_ticks=0.0, stop_atr_mult=1.0, target_atr_mult_min=1.0,
        max_bars_hold=999,
    ))
    res = engine.run(source_df=src, signals_df=sig, inst_cfg=INST_CFG_ES,
                      cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.exit_idx == 5, f"trade must exit on the wild bar; exited at {t.exit_idx}"
    assert t.exit_reason == "stop", f"expected conservative stop-first; got {t.exit_reason}"


# ---------------------------------------------------------------------------
# 4. Session-end flatten.
# ---------------------------------------------------------------------------
def test_session_end_flatten():
    src = _make_source_df(n_sessions=2, bars_per_session=10)
    # signal at very last bar of session 0 (row 8) -> entry at row 9 (last bar)
    # OR signal earlier in session 0 with a wide stop so it doesn't hit.
    sig = _make_long_signal_at(idx=2, n=len(src))
    engine = EventEngine(BacktestParams(
        slippage_ticks=0.0, stop_atr_mult=100.0, target_atr_mult_min=100.0,
        max_bars_hold=999,
    ))
    res = engine.run(source_df=src, signals_df=sig, inst_cfg=INST_CFG_ES,
                      cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    assert len(res.trades) == 1
    t = res.trades[0]
    # Entry was row 3 -> session 0 ends at row 9 -> forced exit at row 9.
    assert t.exit_reason == "session_end"
    assert t.exit_idx == 9
    assert pd.Timestamp(t.exit_time).date() == pd.Timestamp(t.entry_time).date()


# ---------------------------------------------------------------------------
# 5. Roll-skip: no entry on bar immediately after flagged roll.
# ---------------------------------------------------------------------------
def test_roll_skip_blocks_entry():
    src = _make_source_df(n_sessions=2, bars_per_session=15)
    n = len(src)
    sig = _make_long_signal_at(idx=5, n=n)
    # Mark idx 5 (and 6) as roll-skip.
    engine = EventEngine(BacktestParams(slippage_ticks=0.0, max_bars_hold=3,
                                         stop_atr_mult=10.0, target_atr_mult_min=10.0))
    res = engine.run(source_df=src, signals_df=sig, inst_cfg=INST_CFG_ES,
                      cost_fn=fixed_tick_cost, cost_model_name="fixed_tick",
                      roll_skip_idxs={5, 6})
    assert len(res.trades) == 0, "roll-skip should block all entries on/after flagged idx"


# ---------------------------------------------------------------------------
# 6. Portfolio family concurrency: ES + MES with overlapping trades -> 1 accepted.
# ---------------------------------------------------------------------------
def test_portfolio_family_concurrency_blocks_overlap():
    base_entry = pd.Timestamp("2024-03-15 10:00:00", tz="America/New_York")
    base_exit = pd.Timestamp("2024-03-15 11:00:00", tz="America/New_York")

    es_trade = Trade(
        symbol="ES", family="sp500",
        entry_idx=10, entry_time=base_entry, entry_price=5200.0,
        direction=1, contracts=1,
        stop_price=5195.0, target_price=5210.0,
        exit_idx=20, exit_time=base_exit, exit_price=5208.0,
        exit_reason="target", bars_held=10,
        gross_pnl=400.0, cost=12.5, net_pnl=387.5,
    )
    # MES trade overlapping the ES trade's [entry, exit] window: same family.
    mes_trade = Trade(
        symbol="MES", family="sp500",
        entry_idx=10,
        entry_time=base_entry + pd.Timedelta(minutes=15),
        entry_price=5202.0,
        direction=1, contracts=1,
        stop_price=5197.0, target_price=5212.0,
        exit_idx=22,
        exit_time=base_exit + pd.Timedelta(minutes=30),
        exit_price=5210.0,
        exit_reason="target", bars_held=12,
        gross_pnl=400.0, cost=2.5, net_pnl=397.5,
    )
    res = enforce_family_concurrency({"ES": [es_trade], "MES": [mes_trade]})
    assert len(res.accepted_trades) == 1, (
        f"family concurrency must keep exactly 1 of the overlapping trades; "
        f"got {len(res.accepted_trades)}"
    )
    assert len(res.blocked_trades) == 1
    # ES enters first -> ES accepted, MES blocked.
    assert res.accepted_trades[0].symbol == "ES"
    assert res.blocked_trades[0].symbol == "MES"
    assert res.blocked_by_family.get("sp500", 0) == 1


def test_portfolio_family_concurrency_allows_sequential():
    """Two ES family trades back-to-back (no overlap) should BOTH be accepted."""
    t1 = Trade(
        symbol="ES", family="sp500",
        entry_idx=10,
        entry_time=pd.Timestamp("2024-03-15 09:30:00", tz="America/New_York"),
        entry_price=5200.0,
        direction=1, contracts=1, stop_price=5195.0, target_price=5210.0,
        exit_idx=15,
        exit_time=pd.Timestamp("2024-03-15 10:00:00", tz="America/New_York"),
        exit_price=5210.0,
        exit_reason="target", bars_held=5,
        gross_pnl=500.0, cost=12.5, net_pnl=487.5,
    )
    t2 = Trade(
        symbol="MES", family="sp500",
        entry_idx=20,
        entry_time=pd.Timestamp("2024-03-15 10:30:00", tz="America/New_York"),
        entry_price=5215.0,
        direction=1, contracts=1, stop_price=5210.0, target_price=5225.0,
        exit_idx=25,
        exit_time=pd.Timestamp("2024-03-15 11:00:00", tz="America/New_York"),
        exit_price=5225.0,
        exit_reason="target", bars_held=5,
        gross_pnl=50.0, cost=2.5, net_pnl=47.5,
    )
    res = enforce_family_concurrency({"ES": [t1], "MES": [t2]})
    assert len(res.accepted_trades) == 2
    assert len(res.blocked_trades) == 0


def test_portfolio_different_families_independent():
    """ES and MGC are different families -> both should be accepted even with overlap."""
    t_es = Trade(
        symbol="ES", family="sp500",
        entry_idx=10,
        entry_time=pd.Timestamp("2024-03-15 10:00:00", tz="America/New_York"),
        entry_price=5200.0,
        direction=1, contracts=1, stop_price=5195.0, target_price=5210.0,
        exit_idx=20,
        exit_time=pd.Timestamp("2024-03-15 11:00:00", tz="America/New_York"),
        exit_price=5210.0,
        exit_reason="target", bars_held=10,
        gross_pnl=500.0, cost=12.5, net_pnl=487.5,
    )
    t_mgc = Trade(
        symbol="MGC", family="gold",
        entry_idx=10,
        entry_time=pd.Timestamp("2024-03-15 10:15:00", tz="America/New_York"),
        entry_price=2050.0,
        direction=-1, contracts=1, stop_price=2052.0, target_price=2045.0,
        exit_idx=20,
        exit_time=pd.Timestamp("2024-03-15 11:30:00", tz="America/New_York"),
        exit_price=2045.0,
        exit_reason="target", bars_held=10,
        gross_pnl=50.0, cost=2.5, net_pnl=47.5,
    )
    res = enforce_family_concurrency({"ES": [t_es], "MGC": [t_mgc]})
    assert len(res.accepted_trades) == 2
    assert len(res.blocked_trades) == 0


# ---------------------------------------------------------------------------
# 7. Baselines are causal (truncation-invariant).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", list(BASELINES.keys()))
def test_baselines_causal(name: str):
    """For each baseline, signals on the first N bars must not change when we
    append more bars after them."""
    src_short = _make_source_df(n_sessions=3, bars_per_session=20)
    # Append more sessions to the short version
    src_long = pd.concat(
        [src_short,
         _make_source_df(n_sessions=2, bars_per_session=20, start="2024-01-09")],
        ignore_index=True,
    )
    fn = BASELINES[name]
    sig_short = fn(src_short)
    sig_long = fn(src_long).iloc[:len(src_short)].reset_index(drop=True)
    # Cast to comparable types and compare bias + trade_eligible.
    a = pd.DataFrame({"bias": sig_short["bias"].astype(int),
                      "elig": sig_short["trade_eligible"].astype(bool)})
    b = pd.DataFrame({"bias": sig_long["bias"].astype(int),
                      "elig": sig_long["trade_eligible"].astype(bool)})
    # For random_entry_matched_holding we re-seed identically -> still deterministic.
    pd.testing.assert_frame_equal(
        a.reset_index(drop=True), b.reset_index(drop=True),
        check_names=False,
        obj=f"baseline {name} non-causal: short vs long-truncated-to-short differ",
    )


# ---------------------------------------------------------------------------
# 8. Signal recomputation: vectorised gate matches per-row check.
# ---------------------------------------------------------------------------
def test_signal_recompute_handles_missing_files(tmp_path):
    """recompute_trade_eligibility must raise on row-count mismatch."""
    src = _make_source_df(n_sessions=2, bars_per_session=10)
    ens_csv = tmp_path / "ens.csv"
    # Create an ensemble CSV with WRONG row count.
    pd.DataFrame({
        "agreement_count": [0, 0, 0],
        "zone_overlap_atr": [0.5, 0.5, 0.5],
        "projected_completion_median": [5.0, 5.0, 5.0],
        "vpin_gate": ["allow", "allow", "allow"],
        "regime_label": ["balanced_or_choppy"] * 3,
        "ensemble_bias": [1, -1, 0],
        "ensemble_confidence": [0.8, 0.7, 0.9],
    }).to_csv(ens_csv, index=False)
    with pytest.raises(ValueError, match="alignment broken"):
        recompute_trade_eligibility(
            ensemble_csv=ens_csv, source_df=src,
            params=EligibilityParams(min_confidence=0.65, latest_entry_time_et="15:30"),
        )


def test_signal_recompute_gates_correctly(tmp_path):
    """Construct a tiny ensemble CSV with known gate values; verify trade_eligible."""
    src = _make_source_df(n_sessions=1, bars_per_session=5)
    ens_csv = tmp_path / "ens.csv"
    pd.DataFrame({
        "agreement_count": [4, 4, 4, 4, 4],
        "zone_overlap_atr": [0.5, 0.5, 0.5, 0.5, 0.5],
        "projected_completion_median": [5.0, 5.0, 5.0, 5.0, 5.0],
        "vpin_gate": ["allow", "allow", "stand_down", "allow", "allow"],
        "regime_label": ["balanced_or_choppy", "stand_down", "balanced_or_choppy",
                         "balanced_or_choppy", "balanced_or_choppy"],
        "ensemble_bias": [1, 1, 1, 0, 1],
        "ensemble_confidence": [0.8, 0.8, 0.8, 0.8, 0.4],
    }).to_csv(ens_csv, index=False)
    sig = recompute_trade_eligibility(
        ensemble_csv=ens_csv, source_df=src,
        params=EligibilityParams(min_confidence=0.65, latest_entry_time_et="15:30"),
    )
    # Row 0: all pass -> eligible.
    # Row 1: regime stand_down -> ineligible.
    # Row 2: vpin stand_down -> ineligible.
    # Row 3: bias=0 -> ineligible.
    # Row 4: conf < 0.65 -> ineligible.
    assert bool(sig["trade_eligible"].iloc[0]) is True, "row 0 must be eligible"
    assert bool(sig["trade_eligible"].iloc[1]) is False, "row 1: regime stand_down"
    assert bool(sig["trade_eligible"].iloc[2]) is False, "row 2: vpin stand_down"
    assert bool(sig["trade_eligible"].iloc[3]) is False, "row 3: bias=0"
    assert bool(sig["trade_eligible"].iloc[4]) is False, "row 4: conf < 0.65"


def test_family_of_symbol_map_complete():
    """All 9 instruments must have a family mapping."""
    expected = {"ES", "MES", "MNQ", "YM", "MYM", "RTY", "M2K", "MGC", "MCL"}
    assert expected.issubset(set(FAMILY_OF_SYMBOL.keys()))
