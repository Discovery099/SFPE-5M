# SFPE-5M — Phase 5 Summary (v1.4)

_Strict ordering: trade-count audit FIRST → metrics → equity curves → stress windows → baseline comparison → slippage sensitivity._

## Audit gate

✅ **PASS** — portfolio ≥ 200 trades at conf=0.65, and every active instrument ≥ 50 trades.

## Portfolio (family-concurrency-enforced) — primary cost model 1× slippage

| Conf | n_trades | net_profit | PF | Sharpe | Max DD | Win rate |
|---|---|---|---|---|---|---|
| 0.50 | 8,145 | -279,493 | 0.80 | -1.64 | -279,644 | 49.2% |
| 0.65 | 5,852 | -227,930 | 0.79 | -1.78 | -229,894 | 48.8% |

## Per-instrument summary (conf=0.65, fixed_tick, 1× slippage)

| Symbol | n_trades | net_profit | PF | Sharpe | Max DD | Win rate |
|---|---|---|---|---|---|---|
| ES | 871 | -48,294 | 0.70 | -2.54 | -48,439 | 46.0% |
| MES | 907 | -43,698 | 0.71 | -2.56 | -43,852 | 48.5% |
| MNQ | 821 | -22,987 | 0.86 | -1.19 | -26,511 | 47.9% |
| YM | 823 | -19,775 | 0.84 | -1.30 | -21,966 | 48.2% |
| MYM | 810 | -16,310 | 0.89 | -0.88 | -18,523 | 50.7% |
| RTY | 841 | -31,514 | 0.78 | -1.90 | -33,520 | 48.8% |
| M2K | 787 | -36,995 | 0.77 | -2.06 | -37,337 | 48.2% |
| MGC | 495 | -20,119 | 0.79 | -1.79 | -20,391 | 50.3% |
| MCL | 288 | -31,120 | 0.60 | -3.99 | -32,143 | 46.2% |

## Slippage sensitivity (fixed_tick cost, per confidence threshold)

| conf | slip× | total_trades | total_net_profit | mean_PF | mean_Sharpe |
|---|---|---|---|---|---|
| 0.50 | 1× | 9,627 | -354,753 | 0.79 | -1.86 |
| 0.50 | 2× | 9,646 | -607,781 | 0.60 | -3.77 |
| 0.50 | 3× | 9,655 | -800,477 | 0.47 | -5.43 |
| 0.65 | 1× | 6,643 | -270,813 | 0.77 | -2.02 |
| 0.65 | 2× | 6,630 | -471,664 | 0.60 | -3.98 |
| 0.65 | 3× | 6,644 | -628,729 | 0.46 | -5.75 |

## Stress windows (primary variant conf=0.65 1× fixed_tick)

| window | total_trades | total_net_pnl | mean_win_rate |
|---|---|---|---|
| banks | 501 | -31,912 | 45.7% |
| close_30min | 162 | -2,415 | 38.7% |
| covid | 0 | 0 | 0.0% |
| open_30min | 3 | 835 | 22.2% |
| rates | 677 | -34,090 | 48.6% |

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
| STRATEGY (conf=0.65) | 738 | -30,090 | 0.77 | -2.02 | 48.3% |

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