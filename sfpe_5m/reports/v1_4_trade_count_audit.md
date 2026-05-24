# Phase 5 Step — Trade Count Audit (PRE-PF / PRE-SHARPE)

_Per user lock: PF / Sharpe are not statistically meaningful on <200 portfolio trades or <50 per-active-instrument trades._


## Per-instrument per-threshold breakdown

| Symbol | Conf | Eligible bars | Blocked-by-roll-skip | Trades | Conversion (trades/eligible) | Per-instr ≥50? |
|---|---|---|---|---|---|---|
| ES | 0.50 | 2,086 | 40 | 1,275 | 61.1% | ✅ |
| ES | 0.65 | 1,343 | 30 | 871 | 64.9% | ✅ |
| MES | 0.50 | 2,129 | 57 | 1,294 | 60.8% | ✅ |
| MES | 0.65 | 1,422 | 41 | 907 | 63.8% | ✅ |
| MNQ | 0.50 | 1,973 | 55 | 1,214 | 61.5% | ✅ |
| MNQ | 0.65 | 1,242 | 40 | 821 | 66.1% | ✅ |
| YM | 0.50 | 1,861 | 33 | 1,159 | 62.3% | ✅ |
| YM | 0.65 | 1,214 | 20 | 823 | 67.8% | ✅ |
| MYM | 0.50 | 1,864 | 29 | 1,189 | 63.8% | ✅ |
| MYM | 0.65 | 1,204 | 19 | 810 | 67.3% | ✅ |
| RTY | 0.50 | 1,971 | 33 | 1,190 | 60.4% | ✅ |
| RTY | 0.65 | 1,302 | 17 | 841 | 64.6% | ✅ |
| M2K | 0.50 | 1,874 | 22 | 1,131 | 60.4% | ✅ |
| M2K | 0.65 | 1,241 | 11 | 787 | 63.4% | ✅ |
| MGC | 0.50 | 1,489 | 130 | 725 | 48.7% | ✅ |
| MGC | 0.65 | 947 | 83 | 495 | 52.3% | ✅ |
| MCL | 0.50 | 825 | 87 | 450 | 54.5% | ✅ |
| MCL | 0.65 | 477 | 46 | 288 | 60.4% | ✅ |

## Portfolio totals by confidence threshold

| Confidence | Portfolio total trades | ≥ 200? |
|---|---|---|
| 0.50 | 9,627 | ✅ |
| 0.65 | 6,643 | ✅ |

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