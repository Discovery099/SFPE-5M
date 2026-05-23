# SFPE-5M  —  Data Integrity Summary (Phase 1)

Total instruments processed: **9**

Total roll candidates flagged: **4,551**


## Per-instrument verdict

| Symbol | Calendar | Bars | Sessions | Median bars/sess | Dups | OHLC viol | Bad vol | Zero-vol | Outliers | Missing gaps | Short sess | Out-of-RTH | Verdict |
|--------|----------|------|----------|------------------|------|-----------|---------|----------|----------|--------------|------------|------------|---------|
| ES | RTH_eq | 122,295 | 1,594 | 78 | 0 | 0 | 0 | 7 | 0 | 0 | 2 | 0 | ✅ PASS |
| MES | RTH_eq | 122,295 | 1,594 | 78 | 0 | 0 | 0 | 7 | 0 | 0 | 2 | 0 | ✅ PASS |
| MNQ | RTH_eq | 122,295 | 1,594 | 78 | 0 | 0 | 0 | 7 | 0 | 0 | 2 | 0 | ✅ PASS |
| YM | RTH_eq | 122,241 | 1,593 | 78 | 0 | 0 | 0 | 7 | 0 | 0 | 1 | 0 | ✅ PASS |
| MYM | RTH_eq | 122,241 | 1,593 | 78 | 0 | 0 | 0 | 7 | 0 | 0 | 1 | 0 | ✅ PASS |
| RTY | RTH_eq | 122,292 | 1,594 | 78 | 0 | 0 | 0 | 6 | 0 | 0 | 2 | 0 | ✅ PASS |
| M2K | RTH_eq | 122,292 | 1,594 | 78 | 0 | 0 | 0 | 6 | 0 | 0 | 2 | 0 | ✅ PASS |
| MGC | RTH_comex | 95,375 | 1,594 | 60 | 0 | 0 | 0 | 786 | 7 | 0 | 1 | 3160 | ⚠️ WARN |
| MCL | RTH_nymex | 79,229 | 1,202 | 66 | 0 | 0 | 0 | 195 | 0 | 0 | 0 | 0 | ✅ PASS |

## Notes

- **ES**: zero_volume_bars=7 (kept, tagged) ; short_sessions=2
- **MES**: zero_volume_bars=7 (kept, tagged) ; short_sessions=2
- **MNQ**: zero_volume_bars=7 (kept, tagged) ; short_sessions=2
- **YM**: zero_volume_bars=7 (kept, tagged) ; short_sessions=1
- **MYM**: zero_volume_bars=7 (kept, tagged) ; short_sessions=1
- **RTY**: zero_volume_bars=6 (kept, tagged) ; short_sessions=2
- **M2K**: zero_volume_bars=6 (kept, tagged) ; short_sessions=2
- **MGC**: out_of_rth_bars=3160 (excluded from synthetic engines) ; zero_volume_bars=786 (kept, tagged) ; outlier_bars=7 (|ret| > 10*ATR) ; short_sessions=1
- **MCL**: zero_volume_bars=195 (kept, tagged)

## Roll candidates

- **ES.v.0**: 440 roll candidates (close→open gap > 5 × ATR_20). See `roll_candidates.csv`.
- **M2K.v.0**: 513 roll candidates (close→open gap > 5 × ATR_20). See `roll_candidates.csv`.
- **MCL.v.0**: 523 roll candidates (close→open gap > 5 × ATR_20). See `roll_candidates.csv`.
- **MES.v.0**: 435 roll candidates (close→open gap > 5 × ATR_20). See `roll_candidates.csv`.
- **MGC.v.0**: 808 roll candidates (close→open gap > 5 × ATR_20). See `roll_candidates.csv`.
- **MNQ.v.0**: 488 roll candidates (close→open gap > 5 × ATR_20). See `roll_candidates.csv`.
- **MYM.v.0**: 418 roll candidates (close→open gap > 5 × ATR_20). See `roll_candidates.csv`.
- **RTY.v.0**: 510 roll candidates (close→open gap > 5 × ATR_20). See `roll_candidates.csv`.
- **YM.v.0**: 416 roll candidates (close→open gap > 5 × ATR_20). See `roll_candidates.csv`.

## Acceptance gate verdict

✅ **PASS / WARN** — no hard-failure conditions detected. Safe to proceed to Phase 2 engines.
