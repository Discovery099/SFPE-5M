"""Phase 5.5 — projection-aware exits (spec §8.3) tests.

Verifies:
  - Strategy exits at projected_close_high (long TP2) when the trajectory hits it.
  - Strategy exits at projected_close_mid (long TP1) partially when configured.
  - Structural stop (absorption_level − buffer×ATR) is used when reason_codes signals override.
  - Synthetic-open ± fallback_buffer × ATR is used when no override.
  - Time-stop honours ceil(projected_completion_median × projection_hold_mult).
  - Baselines KEEP the legacy ATR-based exits (use_projection_exits=False).
  - signals.recompute_trade_eligibility passes through projection columns.
  - derive_structural_stops obeys the priority order absorption > failed_auction > vacuum.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sfpe.backtest import (
    EventEngine, BacktestParams, Trade,
    fixed_tick_cost, trades_to_dataframe,
    BASELINES,
)
from sfpe.backtest.signals import (
    EligibilityParams, StructuralStopParams,
    derive_structural_stops, recompute_trade_eligibility,
)


INST_CFG_ES = dict(
    symbol="ES", family="sp500",
    point_value=50.0, tick_size=0.25, tick_value=12.5,
)


def _make_source_df(n_sessions: int = 1, bars_per_session: int = 30,
                    start: str = "2024-01-02", base: float = 5000.0,
                    drift: float = 0.5) -> pd.DataFrame:
    rows = []
    sessions = pd.bdate_range(start=start, periods=n_sessions)
    for sd in sessions:
        for b in range(bars_per_session):
            ts = (pd.Timestamp(sd) + pd.Timedelta(minutes=9 * 60 + 30 + b * 5)
                  ).tz_localize("America/New_York")
            mid = base + b * drift
            rows.append(dict(
                timestamp=ts, symbol="ES",
                open=mid, high=mid + 0.5, low=mid - 0.5, close=mid,
                volume=1000.0, session_date=sd.date(),
                bar_index_in_session=b,
                is_first_bar_of_session=(b == 0),
                is_last_bar_of_session=(b == bars_per_session - 1),
                atr_20=2.0,
            ))
    return pd.DataFrame(rows)


def _make_proj_signal_frame(
    n: int, *, signal_idx: int, direction: int,
    entry_price: float, tp1: float, tp2: float,
    stop_long: float = float("nan"), stop_short: float = float("nan"),
    has_struct: bool = False, synth_anchor: float = float("nan"),
    proj_completion_median: float = 6.0,
) -> pd.DataFrame:
    sig = pd.DataFrame({
        "bias": np.zeros(n, dtype=int),
        "trade_eligible": np.zeros(n, dtype=bool),
        "ensemble_confidence": np.full(n, 0.7, dtype=float),
        "regime_label": np.array(["balanced_or_choppy"] * n, dtype=object),
        "vpin_gate": np.array(["allow"] * n, dtype=object),
        "session_phase": np.array([""] * n, dtype=object),
        "projected_close_low": np.full(n, np.nan),
        "projected_close_mid": np.full(n, np.nan),
        "projected_close_high": np.full(n, np.nan),
        "projected_completion_median": np.full(n, proj_completion_median),
        "structural_stop_long": np.full(n, np.nan),
        "structural_stop_short": np.full(n, np.nan),
        "has_structural_stop": np.zeros(n, dtype=bool),
        "synthetic_open_anchor": np.full(n, np.nan),
        "roll_spread_proxy": np.zeros(n),
    })
    sig.loc[signal_idx, "bias"] = direction
    sig.loc[signal_idx, "trade_eligible"] = True
    sig.loc[signal_idx, "projected_close_mid"] = tp1
    if direction > 0:
        sig.loc[signal_idx, "projected_close_high"] = tp2
        sig.loc[signal_idx, "projected_close_low"] = entry_price - 5.0  # arbitrary
    else:
        sig.loc[signal_idx, "projected_close_low"] = tp2
        sig.loc[signal_idx, "projected_close_high"] = entry_price + 5.0
    sig.loc[signal_idx, "structural_stop_long"] = stop_long
    sig.loc[signal_idx, "structural_stop_short"] = stop_short
    sig.loc[signal_idx, "has_structural_stop"] = bool(has_struct)
    sig.loc[signal_idx, "synthetic_open_anchor"] = synth_anchor
    return sig


# ---------------------------------------------------------------------------
# 1. Strategy exits at TP2 (projected_close_high) for LONG when target hit.
# ---------------------------------------------------------------------------
def test_strategy_exits_at_projected_close_high_long():
    src = _make_source_df(n_sessions=1, bars_per_session=30,
                           base=5000.0, drift=0.0)
    n = len(src)
    # Plant a wide upward swing on bars 3..6 that touches both TP1 and TP2.
    src.loc[3, "high"] = 5012.0
    src.loc[4, "high"] = 5020.0       # touches TP2 = 5018
    sig = _make_proj_signal_frame(
        n, signal_idx=0, direction=1,
        entry_price=5000.0,
        tp1=5010.0, tp2=5018.0,
        synth_anchor=5000.0,
    )
    p = BacktestParams(
        use_projection_exits=True, slippage_ticks=0.0,
        risk_per_trade=0.005,  # small contracts -> probably 1, no partial
        fallback_buffer_atr_mult=0.5,
    )
    engine = EventEngine(p)
    res = engine.run(source_df=src, signals_df=sig, inst_cfg=INST_CFG_ES,
                      cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.use_projection_exits is True
    assert t.target_price == pytest.approx(5018.0), (
        f"strategy target must be projected_close_high; got {t.target_price}"
    )
    # Trade should exit at TP2 since bar 4 high >= 5018.
    assert t.exit_reason in ("tp2", "tp2_after_tp1"), (
        f"expected tp2 exit; got {t.exit_reason}"
    )


# ---------------------------------------------------------------------------
# 2. Strategy uses structural stop when has_structural_stop is True.
# ---------------------------------------------------------------------------
def test_strategy_uses_structural_stop_when_available():
    src = _make_source_df(n_sessions=1, bars_per_session=30,
                           base=5000.0, drift=0.0)
    n = len(src)
    # Force a downward stab on bar 3 that hits the structural stop = 4994.
    src.loc[3, "low"] = 4993.0  # below structural_stop=4994
    sig = _make_proj_signal_frame(
        n, signal_idx=0, direction=1,
        entry_price=5000.0,
        tp1=5010.0, tp2=5018.0,
        stop_long=4994.0, stop_short=float("nan"),
        has_struct=True,
        synth_anchor=5000.0,
    )
    p = BacktestParams(use_projection_exits=True, slippage_ticks=0.0)
    engine = EventEngine(p)
    res = engine.run(source_df=src, signals_df=sig, inst_cfg=INST_CFG_ES,
                      cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.stop_price == pytest.approx(4994.0), (
        f"strategy must use structural_stop_long when available; got {t.stop_price}"
    )
    assert t.exit_reason in ("stop", "stop_after_tp1")


# ---------------------------------------------------------------------------
# 3. Synthetic-open ± fallback × ATR is used when no structural override.
# ---------------------------------------------------------------------------
def test_strategy_uses_synthetic_open_fallback_when_no_structural():
    src = _make_source_df(n_sessions=1, bars_per_session=30,
                           base=5000.0, drift=0.0)
    n = len(src)
    # Source[0].open = 5000 (synth_anchor). ATR=2. fallback_buffer=0.5
    # -> long stop = 5000 - 0.5*2 = 4999.
    sig = _make_proj_signal_frame(
        n, signal_idx=0, direction=1,
        entry_price=5000.0,
        tp1=5010.0, tp2=5018.0,
        has_struct=False,
        synth_anchor=5000.0,
    )
    p = BacktestParams(
        use_projection_exits=True, slippage_ticks=0.0,
        fallback_buffer_atr_mult=0.5,
    )
    engine = EventEngine(p)
    res = engine.run(source_df=src, signals_df=sig, inst_cfg=INST_CFG_ES,
                      cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    assert len(res.trades) == 1
    t = res.trades[0]
    # synth_open - 0.5*atr (where atr = atr at bar 1 = 2.0) = 5000 - 1.0 = 4999.
    assert t.stop_price == pytest.approx(4999.0), (
        f"fallback stop expected at synth_anchor - 0.5*ATR; got {t.stop_price}"
    )


# ---------------------------------------------------------------------------
# 4. Time-stop = ceil(projected_completion_median * projection_hold_mult).
# ---------------------------------------------------------------------------
def test_strategy_time_stop_from_projected_completion_median():
    src = _make_source_df(n_sessions=1, bars_per_session=30,
                           base=5000.0, drift=0.0)
    n = len(src)
    sig = _make_proj_signal_frame(
        n, signal_idx=0, direction=1,
        entry_price=5000.0,
        tp1=5050.0, tp2=5100.0,                  # very far targets, never hit
        stop_long=4900.0, has_struct=True,       # very far stop, never hit
        proj_completion_median=4.0,              # 4 bars
        synth_anchor=5000.0,
    )
    p = BacktestParams(
        use_projection_exits=True, slippage_ticks=0.0,
        projection_hold_mult=1.5,                # ceil(4 * 1.5) = 6 bars max hold
    )
    engine = EventEngine(p)
    res = engine.run(source_df=src, signals_df=sig, inst_cfg=INST_CFG_ES,
                      cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.exit_reason in ("time_stop", "time_stop_after_tp1")
    # Entry at idx 1, max_hold = 6, so exit at idx 7.
    assert t.exit_idx == 7, f"expected time-stop exit at idx 7; got {t.exit_idx}"


# ---------------------------------------------------------------------------
# 5. TP1 partial: when contracts >= 2, half exit at TP1 then runner to TP2.
# ---------------------------------------------------------------------------
def test_strategy_tp1_partial_then_runner():
    src = _make_source_df(n_sessions=1, bars_per_session=30,
                           base=5000.0, drift=0.0)
    n = len(src)
    # Bar 3 reaches TP1=5010 only; bar 8 reaches TP2=5020.
    src.loc[3, "high"] = 5011.0  # touches TP1
    src.loc[8, "high"] = 5021.0  # touches TP2
    sig = _make_proj_signal_frame(
        n, signal_idx=0, direction=1,
        entry_price=5000.0,
        tp1=5010.0, tp2=5020.0,
        stop_long=4900.0, has_struct=True,
        synth_anchor=5000.0,
    )
    # Force contracts=2 by setting starting equity high + risk modest.
    p = BacktestParams(
        starting_equity=10_000_000.0,             # huge equity -> many contracts
        risk_per_trade=0.02,                      # 2% risk
        use_projection_exits=True, slippage_ticks=0.0,
        tp1_partial_fraction=0.5,
    )
    engine = EventEngine(p)
    res = engine.run(source_df=src, signals_df=sig, inst_cfg=INST_CFG_ES,
                      cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.contracts >= 2
    assert t.tp1_hit is True, "TP1 must be marked hit"
    assert t.tp1_contracts == int(round(t.contracts * 0.5))
    assert t.runner_contracts == t.contracts - t.tp1_contracts
    assert t.tp1_idx == 3
    assert t.exit_reason in ("tp2_after_tp1",)
    assert t.exit_idx == 8


# ---------------------------------------------------------------------------
# 6. When contracts == 1, no partial -> TP2 only.
# ---------------------------------------------------------------------------
def test_no_partial_when_one_contract():
    src = _make_source_df(n_sessions=1, bars_per_session=30,
                           base=5000.0, drift=0.0)
    n = len(src)
    src.loc[3, "high"] = 5011.0  # would touch TP1
    src.loc[6, "high"] = 5021.0  # would touch TP2
    sig = _make_proj_signal_frame(
        n, signal_idx=0, direction=1,
        entry_price=5000.0,
        tp1=5010.0, tp2=5020.0,
        stop_long=4900.0, has_struct=True,
        synth_anchor=5000.0,
    )
    # Tiny equity -> only 1 contract possible.
    p = BacktestParams(
        starting_equity=2_000.0,
        risk_per_trade=0.005,
        use_projection_exits=True, slippage_ticks=0.0,
    )
    engine = EventEngine(p)
    res = engine.run(source_df=src, signals_df=sig, inst_cfg=INST_CFG_ES,
                      cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.contracts == 1
    assert t.tp1_contracts == 0
    assert t.runner_contracts == 1
    assert t.tp1_hit is False or t.exit_reason == "tp2"
    # The trade should exit at TP2 (idx 6) without intervening TP1 partial.


# ---------------------------------------------------------------------------
# 7. Conservative stop-first preserved with projection exits.
# ---------------------------------------------------------------------------
def test_projection_exits_conservative_stop_first_on_same_bar():
    src = _make_source_df(n_sessions=1, bars_per_session=15,
                           base=5000.0, drift=0.0)
    n = len(src)
    # Bar 3 spans BOTH stop (4994) and TP2 (5020): high=5021, low=4993.
    src.loc[3, "high"] = 5021.0
    src.loc[3, "low"] = 4993.0
    sig = _make_proj_signal_frame(
        n, signal_idx=0, direction=1,
        entry_price=5000.0,
        tp1=5010.0, tp2=5020.0,
        stop_long=4994.0, has_struct=True,
        synth_anchor=5000.0,
    )
    p = BacktestParams(use_projection_exits=True, slippage_ticks=0.0)
    engine = EventEngine(p)
    res = engine.run(source_df=src, signals_df=sig, inst_cfg=INST_CFG_ES,
                      cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    t = res.trades[0]
    # Conservative -> stop wins same-bar tie.
    assert t.exit_reason in ("stop", "stop_after_tp1")


# ---------------------------------------------------------------------------
# 8. Baselines KEEP legacy ATR exits (use_projection_exits=False).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", list(BASELINES.keys()))
def test_baselines_keep_atr_exits(name: str):
    """Baselines must NOT use projection-aware exits — required for fair comparison."""
    src = _make_source_df(n_sessions=2, bars_per_session=20,
                           base=5000.0, drift=0.0)
    fn = BASELINES[name]
    signals = fn(src)
    signals = signals.copy()
    signals["roll_spread_proxy"] = 0.0
    p = BacktestParams(use_projection_exits=False, slippage_ticks=0.0)
    engine = EventEngine(p)
    res = engine.run(source_df=src, signals_df=signals, inst_cfg=INST_CFG_ES,
                      cost_fn=fixed_tick_cost, cost_model_name="fixed_tick")
    for t in res.trades:
        assert t.use_projection_exits is False
        assert t.tp1_price is None
        assert t.tp1_contracts == 0
        # exit_reason should be from the legacy vocabulary (not tp2 / tp2_after_tp1).
        assert "tp2" not in t.exit_reason
        assert "after_tp1" not in t.exit_reason


# ---------------------------------------------------------------------------
# 9. derive_structural_stops priority order.
# ---------------------------------------------------------------------------
def test_derive_structural_stops_priority_absorption_wins():
    # Multi-override row: absorption + failed_auction. Absorption must win.
    rc = np.array([
        "override_absorption_bid_absorption;override_failed_auction_+1",
        "override_vacuum_continuation",
        "override_vacuum_reversal",
        "override_failed_auction_-1",
        "",
    ])
    atr = np.full(5, 2.0)
    abs_lvl = np.array([100.0, np.nan, np.nan, np.nan, np.nan])
    vac_ext = np.array([np.nan, 200.0, np.nan, np.nan, np.nan])
    vac_orig = np.array([np.nan, np.nan, 300.0, np.nan, np.nan])
    tpo = np.array([150.0, np.nan, np.nan, 400.0, np.nan])
    sl, ss, hs = derive_structural_stops(
        reason_codes=rc, atr_20=atr,
        absorption_level=abs_lvl, vacuum_extreme=vac_ext,
        vacuum_origin=vac_orig, tpo_target=tpo,
        buffer_atr_mult=0.5,
    )
    # Row 0: absorption wins over failed_auction -> anchor=100, sl=99, ss=101.
    assert sl[0] == pytest.approx(99.0)
    assert ss[0] == pytest.approx(101.0)
    assert hs[0] is np.bool_(True) or hs[0] == True
    # Row 1: vacuum_continuation -> anchor=200.
    assert sl[1] == pytest.approx(199.0)
    # Row 2: vacuum_reversal -> origin=300.
    assert sl[2] == pytest.approx(299.0)
    # Row 3: failed_auction -> 400.
    assert sl[3] == pytest.approx(399.0)
    # Row 4: no override -> NaN.
    assert np.isnan(sl[4])
    assert np.isnan(ss[4])
    assert not hs[4]


# ---------------------------------------------------------------------------
# 10. recompute_trade_eligibility passes through projection columns.
# ---------------------------------------------------------------------------
def test_recompute_passes_projection_columns(tmp_path):
    src = _make_source_df(n_sessions=1, bars_per_session=5,
                           base=5000.0, drift=0.0)
    ens_csv = tmp_path / "ens.csv"
    pd.DataFrame({
        "agreement_count": [4, 4, 4, 4, 4],
        "zone_overlap_atr": [0.5, 0.5, 0.5, 0.5, 0.5],
        "projected_close_low": [4995, 4995, 4995, 4995, 4995],
        "projected_close_mid": [5005, 5005, 5005, 5005, 5005],
        "projected_close_high": [5015, 5015, 5015, 5015, 5015],
        "projected_completion_median": [5.0, 5.0, 5.0, 5.0, 5.0],
        "vpin_gate": ["allow", "allow", "allow", "allow", "allow"],
        "regime_label": ["balanced_or_choppy"] * 5,
        "ensemble_bias": [1, 1, 1, 1, 1],
        "ensemble_confidence": [0.8, 0.8, 0.8, 0.8, 0.8],
        "reason_codes": ["", "override_absorption_bid_absorption", "", "", ""],
        "current_price": [5000, 5000, 5000, 5000, 5000],
    }).to_csv(ens_csv, index=False)
    sig = recompute_trade_eligibility(
        ensemble_csv=ens_csv, source_df=src,
        params=EligibilityParams(min_confidence=0.65, latest_entry_time_et="15:30"),
    )
    # Required v1.5 projection columns must be present.
    for c in ("projected_close_low", "projected_close_mid", "projected_close_high",
              "projected_completion_median", "synthetic_open_anchor"):
        assert c in sig.columns, f"missing projection column {c}"
    # Without feature CSVs, structural_stop_* should be NaN, has_structural_stop=False.
    assert sig["has_structural_stop"].sum() == 0
    assert sig["projected_close_mid"].iloc[0] == pytest.approx(5005.0)


def test_recompute_with_feature_csvs_yields_structural_stop(tmp_path):
    src = _make_source_df(n_sessions=1, bars_per_session=5,
                           base=5000.0, drift=0.0)
    n = len(src)
    ens = pd.DataFrame({
        "agreement_count": [4] * n,
        "zone_overlap_atr": [0.5] * n,
        "projected_close_low": [4995] * n,
        "projected_close_mid": [5005] * n,
        "projected_close_high": [5015] * n,
        "projected_completion_median": [5.0] * n,
        "vpin_gate": ["allow"] * n,
        "regime_label": ["balanced_or_choppy"] * n,
        "ensemble_bias": [1] * n,
        "ensemble_confidence": [0.8] * n,
        "reason_codes": [""] * n,
        "current_price": [5000] * n,
    })
    abs_df = pd.DataFrame({"absorption_level": [np.nan] * n})
    vac_df = pd.DataFrame({"extreme_level": [np.nan] * n, "origin_level": [np.nan] * n})
    tpo_df = pd.DataFrame({"target_level": [np.nan] * n})
    # Plant an absorption override at row 2 with anchor 4990 and ATR=2.
    ens.loc[2, "reason_codes"] = "override_absorption_ask_absorption"
    abs_df.loc[2, "absorption_level"] = 4990.0
    ens.to_csv(tmp_path / "ens.csv", index=False)
    abs_df.to_csv(tmp_path / "abs.csv", index=False)
    vac_df.to_csv(tmp_path / "vac.csv", index=False)
    tpo_df.to_csv(tmp_path / "tpo.csv", index=False)
    sig = recompute_trade_eligibility(
        ensemble_csv=tmp_path / "ens.csv", source_df=src,
        absorption_csv=tmp_path / "abs.csv",
        vacuum_csv=tmp_path / "vac.csv",
        tpo_csv=tmp_path / "tpo.csv",
        params=EligibilityParams(min_confidence=0.65, latest_entry_time_et="15:30"),
        structural_stop_params=StructuralStopParams(structural_buffer_atr_mult=0.5),
    )
    # Row 2 must have has_structural_stop=True; stop_long=4990-1=4989.
    assert bool(sig["has_structural_stop"].iloc[2]) is True
    assert sig["structural_stop_long"].iloc[2] == pytest.approx(4989.0)
    assert sig["structural_stop_short"].iloc[2] == pytest.approx(4991.0)
    # Other rows: no structural stop.
    for r in (0, 1, 3, 4):
        assert bool(sig["has_structural_stop"].iloc[r]) is False
