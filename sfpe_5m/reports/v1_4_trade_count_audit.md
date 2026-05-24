# Phase 5 Step — Trade Count Audit (PRE-PF / PRE-SHARPE)

_Per user lock: PF / Sharpe are not statistically meaningful on <200 portfolio trades or <50 per-active-instrument trades._


## Per-instrument per-threshold breakdown

| Symbol | Conf | Eligible bars | Blocked-by-roll-skip | Trades | Conversion (trades/eligible) | Per-instr ≥50? |
|---|---|---|---|---|---|---|
| ES | 0.50 | 2,086 | 40 | 928 | 44.5% | ✅ |
| ES | 0.65 | 1,343 | 30 | 639 | 47.6% | ✅ |
| MES | 0.50 | 2,129 | 57 | 885 | 41.6% | ✅ |
| MES | 0.65 | 1,422 | 41 | 626 | 44.0% | ✅ |
| MNQ | 0.50 | 1,973 | 55 | 877 | 44.5% | ✅ |
| MNQ | 0.65 | 1,242 | 40 | 586 | 47.2% | ✅ |
| YM | 0.50 | 1,861 | 33 | 833 | 44.8% | ✅ |
| YM | 0.65 | 1,214 | 20 | 579 | 47.7% | ✅ |
| MYM | 0.50 | 1,864 | 29 | 829 | 44.5% | ✅ |
| MYM | 0.65 | 1,204 | 19 | 573 | 47.6% | ✅ |
| RTY | 0.50 | 1,971 | 33 | 810 | 41.1% | ✅ |
| RTY | 0.65 | 1,302 | 17 | 572 | 43.9% | ✅ |
| M2K | 0.50 | 1,874 | 22 | 800 | 42.7% | ✅ |
| M2K | 0.65 | 1,241 | 11 | 572 | 46.1% | ✅ |
| MGC | 0.50 | 1,489 | 130 | 568 | 38.1% | ✅ |
| MGC | 0.65 | 947 | 83 | 381 | 40.2% | ✅ |
| MCL | 0.50 | 825 | 87 | 329 | 39.9% | ✅ |
| MCL | 0.65 | 477 | 46 | 213 | 44.7% | ✅ |

## Portfolio totals by confidence threshold

| Confidence | Portfolio total trades | ≥ 200? |
|---|---|---|
| 0.50 | 6,859 | ✅ |
| 0.65 | 4,741 | ✅ |

## Gate verdict (primary threshold conf=0.65)

✅ **PASS** — portfolio ≥ 200 trades AND every active instrument ≥ 50 trades. Proceeding to full PF / Sharpe / DSR computation.


## User-requested: trades blocked by roll-skip rule

- ES (conf=0.50): 40 of 2,086 eligible-bar signals blocked (1.92%) ✅
- ES (conf=0.65): 30 of 1,343 eligible-bar signals blocked (2.23%) ✅
- MES (conf=0.50): 57 of 2,129 eligible-bar signals blocked (2.68%) ✅
- MES (conf=0.65): 41 of 1,422 eligible-bar signals blocked (2.88%) ✅
- MNQ (conf=0.50): 55 of 1,973 eligible-bar signals blocked (2.79%) ✅
- MNQ (conf=0.65): 40 of 1,242 eligible-bar signals blocked (3.22%) ✅
- YM (conf=0.50): 33 of 1,861 eligible-bar signals blocked (1.77%) ✅
- YM (conf=0.65): 20 of 1,214 eligible-bar signals blocked (1.65%) ✅
- MYM (conf=0.50): 29 of 1,864 eligible-bar signals blocked (1.56%) ✅
- MYM (conf=0.65): 19 of 1,204 eligible-bar signals blocked (1.58%) ✅
- RTY (conf=0.50): 33 of 1,971 eligible-bar signals blocked (1.67%) ✅
- RTY (conf=0.65): 17 of 1,302 eligible-bar signals blocked (1.31%) ✅
- M2K (conf=0.50): 22 of 1,874 eligible-bar signals blocked (1.17%) ✅
- M2K (conf=0.65): 11 of 1,241 eligible-bar signals blocked (0.89%) ✅
- MGC (conf=0.50): 130 of 1,489 eligible-bar signals blocked (8.73%) ⚠️ >5%
- MGC (conf=0.65): 83 of 947 eligible-bar signals blocked (8.76%) ⚠️ >5%
- MCL (conf=0.50): 87 of 825 eligible-bar signals blocked (10.55%) ⚠️ >5%
- MCL (conf=0.65): 46 of 477 eligible-bar signals blocked (9.64%) ⚠️ >5%