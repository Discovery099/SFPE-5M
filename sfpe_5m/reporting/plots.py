"""Plotting utilities for SFPE-5M v1.

v1 produces:
  - session_coverage_heatmap.png: per-instrument bars-per-session over time.
  - engine_bars_per_session.png  (per (engine, symbol)) inside diagnostics.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def session_coverage_heatmap(
    coverage_by_symbol: Dict[str, pd.Series],
    expected_bars_by_symbol: Dict[str, int],
    out_path: Path,
) -> None:
    """Build a heatmap of bars-per-session over time for all instruments.

    coverage_by_symbol: {symbol: pd.Series indexed by session_date, values=bars}
    expected_bars_by_symbol: {symbol: expected_bars_per_session}
    """
    if not coverage_by_symbol:
        return
    symbols = sorted(coverage_by_symbol.keys())
    # Build a unified date index (union of all session_dates).
    all_dates_set = set()
    for s in symbols:
        all_dates_set.update(coverage_by_symbol[s].index.tolist())
    all_dates = sorted(all_dates_set)
    if not all_dates:
        return

    matrix = np.full((len(symbols), len(all_dates)), np.nan, dtype=float)
    date_to_col = {d: i for i, d in enumerate(all_dates)}
    for r, sym in enumerate(symbols):
        ser = coverage_by_symbol[sym]
        exp = expected_bars_by_symbol[sym]
        for d, v in ser.items():
            matrix[r, date_to_col[d]] = (v / exp) * 100.0 if exp > 0 else np.nan

    fig_h = max(2.0, 0.55 * len(symbols))
    fig, ax = plt.subplots(figsize=(14, fig_h))
    im = ax.imshow(
        matrix, aspect="auto", cmap="viridis",
        vmin=0, vmax=110, interpolation="nearest",
    )
    ax.set_yticks(range(len(symbols)))
    ax.set_yticklabels(symbols)
    # x-ticks: 12 evenly spaced labels
    n_ticks = min(12, len(all_dates))
    if n_ticks > 1:
        idxs = np.linspace(0, len(all_dates) - 1, n_ticks).astype(int)
        ax.set_xticks(idxs)
        ax.set_xticklabels([str(all_dates[i]) for i in idxs], rotation=45, ha="right")
    ax.set_title("Session coverage  (bars per session / expected bars  × 100%)")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("% of expected bars")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def engine_bars_histogram(
    bars_df: pd.DataFrame,
    title: str,
    out_path: Path,
) -> None:
    """Histogram of synthetic-bars-per-session for one (engine, symbol)."""
    if bars_df.empty:
        return
    counts = bars_df.groupby("session_date").size().values
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(counts, bins=range(int(counts.min()), int(counts.max()) + 2), edgecolor="black")
    ax.set_title(title)
    ax.set_xlabel("synthetic bars per session")
    ax.set_ylabel("sessions")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
