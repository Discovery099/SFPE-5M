# SFPE-5M — Phase 5 Summary (v1.4)

_Strict ordering: trade-count audit FIRST → metrics → equity curves → stress windows → baseline comparison → slippage sensitivity._

## Audit gate

✅ **PASS** — portfolio ≥ 200 trades at conf=0.65, and every active instrument ≥ 50 trades.

## Portfolio (family-concurrency-enforced) — primary cost model 1× slippage

| Conf | n_trades | net_profit | PF | Sharpe | Max DD | Win rate |
|---|---|---|---|---|---|---|
| 0.50 | 5,735 | -194,488 | 0.78 | -1.56 | -196,423 | 42.0% |
| 0.65 | 4,110 | -146,257 | 0.77 | -1.63 | -148,758 | 41.6% |

## Per-instrument summary (conf=0.65, fixed_tick, 1× slippage)

| Symbol | n_trades | net_profit | PF | Sharpe | Max DD | Win rate |
|---|---|---|---|---|---|---|
| ES | 639 | -30,061 | 0.73 | -1.93 | -31,673 | 36.3% |
| MES | 626 | -21,313 | 0.75 | -1.77 | -21,558 | 40.1% |
| MNQ | 586 | -9,631 | 0.90 | -0.70 | -12,442 | 44.2% |
| YM | 579 | -4,631 | 0.94 | -0.39 | -16,008 | 43.4% |
| MYM | 573 | -11,823 | 0.85 | -1.06 | -12,989 | 46.1% |
| RTY | 572 | -19,654 | 0.78 | -1.62 | -19,999 | 42.7% |
| M2K | 572 | -28,406 | 0.70 | -2.22 | -29,154 | 41.1% |
| MGC | 381 | -15,957 | 0.71 | -2.27 | -16,676 | 43.3% |
| MCL | 213 | -19,706 | 0.57 | -3.52 | -21,616 | 36.6% |

## Slippage sensitivity (fixed_tick cost, per confidence threshold)

| conf | slip× | total_trades | total_net_profit | mean_PF | mean_Sharpe |
|---|---|---|---|---|---|
| 0.50 | 1× | 6,859 | -216,071 | 0.78 | -1.63 |
| 0.50 | 2× | 6,799 | -419,979 | 0.59 | -3.57 |
| 0.50 | 3× | 6,734 | -584,141 | 0.45 | -5.45 |
| 0.65 | 1× | 4,741 | -161,182 | 0.77 | -1.72 |
| 0.65 | 2× | 4,689 | -317,873 | 0.58 | -3.76 |
| 0.65 | 3× | 4,634 | -448,264 | 0.44 | -5.71 |

## Stress windows (primary variant conf=0.65 1× fixed_tick)

| window | total_trades | total_net_pnl | mean_win_rate |
|---|---|---|---|
| banks | 385 | -14,854 | 39.1% |
| close_30min | 113 | -3,025 | 34.3% |
| covid | 0 | 0 | 0.0% |
| open_30min | 3 | 1,231 | 33.3% |
| rates | 443 | -9,962 | 46.0% |

## 10-baseline comparison (mean across active instruments)

| Variant | mean_trades | mean_net | mean_PF | mean_Sharpe | mean_winrate |
|---|---|---|---|---|---|
| atr_breakout | 10206 | -191,507 | 0.75 | -1.60 | 47.3% |
| bollinger_mean_reversion_20 | 7893 | -173,968 | 0.75 | -1.70 | 47.3% |
| buy_and_hold_intraday | 1447 | -54,679 | 0.80 | -1.67 | 47.3% |
| donchian_channel_20 | 6703 | -145,729 | 0.74 | -1.79 | 47.3% |
| ema_crossover_9_21 | 28404 | -424,110 | 0.78 | -1.36 | 47.8% |
| opening_range_breakout | 18638 | -284,375 | 0.78 | -1.31 | 48.1% |
| prior_bar_mean_reversion | 28257 | -433,580 | 0.78 | -1.36 | 47.5% |
| prior_bar_momentum | 28338 | -449,057 | 0.78 | -1.38 | 47.7% |
| random_entry_matched_holding | 1494 | -51,409 | 0.78 | -1.84 | 48.0% |
| vwap_mean_reversion | 21490 | -369,490 | 0.76 | -1.48 | 47.2% |
| STRATEGY (conf=0.65) | 527 | -17,909 | 0.77 | -1.72 | 41.5% |

## Roll-skip blocked-signal counts (per user request)

| Symbol | Conf | Eligible bars | Blocked | % blocked | >5% flag |
|---|---|---|---|---|---|
| ES | 0.50 | 2,086 | 40 | 1.92% | ✅ |
| ES | 0.65 | 1,343 | 30 | 2.23% | ✅ |
| MES | 0.50 | 2,129 | 57 | 2.68% | ✅ |
| MES | 0.65 | 1,422 | 41 | 2.88% | ✅ |
| MNQ | 0.50 | 1,973 | 55 | 2.79% | ✅ |
| MNQ | 0.65 | 1,242 | 40 | 3.22% | ✅ |
| YM | 0.50 | 1,861 | 33 | 1.77% | ✅ |
| YM | 0.65 | 1,214 | 20 | 1.65% | ✅ |
| MYM | 0.50 | 1,864 | 29 | 1.56% | ✅ |
| MYM | 0.65 | 1,204 | 19 | 1.58% | ✅ |
| RTY | 0.50 | 1,971 | 33 | 1.67% | ✅ |
| RTY | 0.65 | 1,302 | 17 | 1.31% | ✅ |
| M2K | 0.50 | 1,874 | 22 | 1.17% | ✅ |
| M2K | 0.65 | 1,241 | 11 | 0.89% | ✅ |
| MGC | 0.50 | 1,489 | 130 | 8.73% | ⚠️ |
| MGC | 0.65 | 947 | 83 | 8.76% | ⚠️ |
| MCL | 0.50 | 825 | 87 | 10.55% | ⚠️ |
| MCL | 0.65 | 477 | 46 | 9.64% | ⚠️ |