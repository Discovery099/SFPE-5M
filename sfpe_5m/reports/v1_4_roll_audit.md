# Phase 5 Step 1 — Roll Detection Audit (legacy v1.0 vs v1.4)

_v1.4 params (user-locked 2026-05-24): **8× ATR_20 gap** + calendar gating to family roll months + **volume z-score ≥ 0.5** on candidate or prior session, **ALL three conditions required**._

_Total flagged candidates — legacy: **4,551**, v1.4: **498**._


## Per-instrument candidate counts

| Symbol | Family | Sessions | Years | Expected/yr | Expected total | **Legacy v1** | **v1.4** | Drop % | v1.4 − expected |
|---|---|---|---|---|---|---|---|---|---|
| ES | sp500 | 1,594 | 6.17 | 4 | 25 | **440** | **30** | 93.2% | +5 |
| MES | sp500 | 1,594 | 6.17 | 4 | 25 | **435** | **31** | 92.9% | +6 |
| MNQ | nasdaq | 1,594 | 6.17 | 4 | 25 | **488** | **41** | 91.6% | +16 |
| YM | dow | 1,593 | 6.17 | 4 | 25 | **416** | **39** | 90.6% | +14 |
| MYM | dow | 1,593 | 6.17 | 4 | 25 | **418** | **34** | 91.9% | +9 |
| RTY | russell | 1,594 | 6.17 | 4 | 25 | **510** | **36** | 92.9% | +11 |
| M2K | russell | 1,594 | 6.17 | 4 | 25 | **513** | **32** | 93.8% | +7 |
| MGC | gold | 1,594 | 6.17 | 6 | 37 | **808** | **150** | 81.4% | +113 |
| MCL | oil | 1,202 | 4.65 | 12 | 56 | **523** | **105** | 79.9% | +49 |
| **TOTAL** | — | — | — | — | **268** | **4,551** | **498** | 89.1% | +230 |

## v1.4 per-instrument condition signature (which conditions fired)

| symbol | gap+cal+vol |
|---|---|
| ES.v.0 | 30 |
| M2K.v.0 | 32 |
| MCL.v.0 | 105 |
| MES.v.0 | 31 |
| MGC.v.0 | 150 |
| MNQ.v.0 | 41 |
| MYM.v.0 | 34 |
| RTY.v.0 | 36 |
| YM.v.0 | 39 |

## Acceptance vs principled expectation

⚠️ **v1.4 total = 498 > 350 (upper of the principled 150–350 band).** Per user instruction, we do not auto-tune; we surface the data and await guidance before proceeding to backtester.

## Family roll-month reference

| Family | Roll months |
|---|---|
| dow | 3,6,9,12 |
| gold | 2,4,6,8,10,12 |
| nasdaq | 3,6,9,12 |
| oil | 1,2,3,4,5,6,7,8,9,10,11,12 |
| russell | 3,6,9,12 |
| sp500 | 3,6,9,12 |