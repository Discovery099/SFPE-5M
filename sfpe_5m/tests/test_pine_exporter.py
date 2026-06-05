"""Tests for src/sfpe/pine_exporter.py.

Verifies:
  - All 9 instruments produce strategy + indicator Pine v6 files.
  - Each file contains the mandatory header block elements (A_STOP warning,
    v1.5-final parameter list, port/approximation matrix).
  - Per-instrument hardcoded constants (point_value, tick_size, commission,
    RTH session) appear correctly in the generated text.
  - Pine v6 specific patterns are present: //@version=6, barstate.isconfirmed,
    math.round_to_mintick.
  - Strategy files contain strategy.entry/exit; indicator files do NOT.
  - Screener contains request.security for every instrument.
  - No leftover Python f-string placeholders or template tokens.
  - No `:=` reassignment on non-`var` declarations in any file (Pine syntax bug).
"""
from __future__ import annotations

import re

import pytest

from sfpe.pine_exporter import (
    INSTRUMENTS, V15_FINAL, build_indicator_pine, build_screener_pine,
    build_strategy_pine,
)


MANDATORY_INSTRUMENTS = {
    "ES", "MES", "MNQ", "YM", "MYM", "RTY", "M2K", "MGC", "MCL",
}


MANDATORY_HEADER_PHRASES = [
    "A_STOP",
    "v1.5-final",
    "NOT FOR LIVE TRADING",
    "PORTED CLEANLY",
    "APPROXIMATED",
    "HARDCODED v1.5-FINAL PARAMETERS",
    "DO NOT MODIFY THESE DEFAULTS",
]

MANDATORY_PINE_V6_PATTERNS = [
    "//@version=6",
    "barstate.isconfirmed",
    "math.round_to_mintick",
    "math.pow",                  # geometric mean confidence
    "ta.atr(20)",
    "ta.percentile_linear_interpolation",
    "hour(time,",                # tz-aware hour
]


def test_all_9_instruments_present_in_registry():
    assert set(INSTRUMENTS.keys()) == MANDATORY_INSTRUMENTS


def test_v15_final_parameter_defaults_locked():
    assert V15_FINAL["structural_buffer_atr_mult"] == 0.5
    assert V15_FINAL["fallback_buffer_atr_mult"] == 0.5
    assert V15_FINAL["projection_hold_mult"] == 1.5
    assert V15_FINAL["tp1_partial_fraction"] == 0.5
    assert V15_FINAL["min_confidence"] == 0.65
    assert V15_FINAL["min_engines_agree"] == 3
    assert V15_FINAL["risk_per_trade"] == 0.005


def _strip_comments(text: str) -> str:
    """Strip Pine line comments (//) so we can search for code patterns
    without false positives from the header comment block."""
    out_lines = []
    for line in text.splitlines():
        # Pine line comment starts at //; remove from there to end of line.
        idx = line.find("//")
        if idx >= 0:
            line = line[:idx]
        out_lines.append(line)
    return "\n".join(out_lines)


@pytest.mark.parametrize("sym", sorted(MANDATORY_INSTRUMENTS))
def test_strategy_pine_emits_required_blocks(sym: str):
    ins = INSTRUMENTS[sym]
    text = build_strategy_pine(ins)
    # Header
    for phrase in MANDATORY_HEADER_PHRASES:
        assert phrase in text, f"{sym} strategy missing required header phrase {phrase!r}"
    # Pine v6 patterns
    for p in MANDATORY_PINE_V6_PATTERNS:
        assert p in text, f"{sym} strategy missing Pine v6 pattern {p!r}"
    # strategy() declaration appears in the actual code (not just header)
    code = _strip_comments(text)
    assert "strategy(\"SFPE-5M" in code
    assert "strategy.entry(" in code
    assert "strategy.exit(" in code
    assert "strategy.commission.cash_per_contract" in code
    # Per-instrument constants present (with the spacing the generator uses).
    assert f"point_value = {ins.point_value}" in code
    assert f"commission_value={ins.commission_per_side}" in code
    # Inputs lock to v1.5-final
    assert f"input.float({V15_FINAL['structural_buffer_atr_mult']}" in code
    assert f"input.float({V15_FINAL['min_confidence']}" in code
    assert f"input.int({V15_FINAL['min_engines_agree']}" in code
    # No Python f-string placeholders leaked
    assert "{ins." not in text
    assert "{V15_FINAL[" not in text


@pytest.mark.parametrize("sym", sorted(MANDATORY_INSTRUMENTS))
def test_indicator_pine_omits_strategy_calls(sym: str):
    ins = INSTRUMENTS[sym]
    text = build_indicator_pine(ins)
    for phrase in MANDATORY_HEADER_PHRASES:
        assert phrase in text
    # Compare CODE only (strip comments — the header documents strategy.* exits
    # as a "ported cleanly" feature; that's prose, not code.)
    code = _strip_comments(text)
    assert "indicator(\"SFPE-5M" in code
    assert "strategy(" not in code
    assert "strategy.entry(" not in code
    assert "strategy.exit(" not in code
    assert "strategy.close_all" not in code
    # alertcondition for indicator-side alerts.
    assert "alertcondition(" in code


def test_screener_uses_request_security_for_all_instruments():
    text = build_screener_pine(INSTRUMENTS)
    code = _strip_comments(text)
    assert "//@version=6" in text   # header version directive
    assert "indicator(" in code
    # Every instrument's TV symbol appears in a request.security call.
    for sym, ins in INSTRUMENTS.items():
        assert f'request.security("{ins.tv_symbol}"' in code
    # One alert() per symbol.
    assert code.count("alert(str.format(") >= len(INSTRUMENTS)
    # Single combined alertcondition disjunction
    assert "SFPE-5M ANY signal" in code


def test_screener_does_not_use_strategy_calls():
    text = build_screener_pine(INSTRUMENTS)
    code = _strip_comments(text)
    assert "strategy.entry(" not in code
    assert "strategy.exit(" not in code
    assert "strategy(" not in code


def _walrus_on_var(text: str) -> list[str]:
    """Return list of `:=` left-hand-side identifiers that are NOT declared
    via `var ` somewhere earlier in the text. A Pine v6 bug if any."""
    var_decls = set(re.findall(r"\bvar\s+\w+\s+(\w+)\s*=", text))
    # Also handle `var array<...> name = ...`
    var_decls |= set(re.findall(r"\bvar\s+array<[^>]+>\s+(\w+)\s*=", text))
    bad = []
    for m in re.finditer(r"^[\s]*(\w+)\s*:=", text, re.MULTILINE):
        name = m.group(1)
        if name not in var_decls:
            bad.append(name)
    return bad


@pytest.mark.parametrize("sym", sorted(MANDATORY_INSTRUMENTS))
def test_no_walrus_on_non_var_in_strategy(sym: str):
    ins = INSTRUMENTS[sym]
    bad = _walrus_on_var(build_strategy_pine(ins))
    assert bad == [], f"{sym} strategy has := on non-var identifiers: {bad}"


@pytest.mark.parametrize("sym", sorted(MANDATORY_INSTRUMENTS))
def test_no_walrus_on_non_var_in_indicator(sym: str):
    ins = INSTRUMENTS[sym]
    bad = _walrus_on_var(build_indicator_pine(ins))
    assert bad == [], f"{sym} indicator has := on non-var identifiers: {bad}"


def test_screener_no_walrus_on_non_var():
    bad = _walrus_on_var(build_screener_pine(INSTRUMENTS))
    assert bad == [], f"screener has := on non-var identifiers: {bad}"


@pytest.mark.parametrize("sym", sorted(MANDATORY_INSTRUMENTS))
def test_int_int_division_promoted_to_float(sym: str):
    """`f = h / i_horizon` would be int/int=int in Pine v6; we promote via
    float(i_horizon)."""
    ins = INSTRUMENTS[sym]
    for text in (build_strategy_pine(ins), build_indicator_pine(ins)):
        # The exact pattern we use:
        assert "f = h / float(i_horizon)" in text


def test_screener_does_not_use_strategy_calls_2():
    text = build_screener_pine(INSTRUMENTS)
    code = _strip_comments(text)
    assert "strategy.entry(" not in code
    assert "strategy.exit(" not in code
    assert "strategy(" not in code


def test_strategy_files_have_per_side_commission_set():
    for sym, ins in INSTRUMENTS.items():
        text = build_strategy_pine(ins)
        # commission_value follows realistic CME 2024 fee table per instrument
        assert f"commission_value={ins.commission_per_side}" in text


def test_session_end_time_per_instrument():
    # Equity instruments must use 16:00 ET; MGC uses 13:00; MCL uses 14:30.
    for sym, ins in INSTRUMENTS.items():
        text = build_strategy_pine(ins)
        end_h = int(ins.rth_end_et[:2])
        end_m = int(ins.rth_end_et[2:])
        assert f"end_h = {end_h}" in text
        assert f"end_m = {end_m}" in text
