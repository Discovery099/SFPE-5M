# Phase 4 Acceptance Gates (spec §11.2)

PASSED 5 of 9 instruments  (threshold: ≥5 to authorize Phase 5)

| Symbol | Family | n_bars | n_high_conf | close_hit@0.65 | dur_hit@0.65 | zone_monotonic | rho | Verdict |
|--------|--------|--------|-------------|----------------|--------------|-----------------|-----|---------|
| ES | sp500 | 122,295 | 2,974 | 0.698 | 0.874 | True | -1.000 | FAIL |
| MES | sp500 | 122,295 | 3,207 | 0.715 | 0.871 | True | -1.000 | PASS |
| MNQ | nasdaq | 122,295 | 2,971 | 0.706 | 0.861 | True | -1.000 | PASS |
| YM | dow | 122,241 | 2,845 | 0.692 | 0.877 | True | -1.000 | FAIL |
| MYM | dow | 122,241 | 2,847 | 0.692 | 0.896 | True | -1.000 | FAIL |
| RTY | russell | 122,292 | 3,001 | 0.700 | 0.865 | True | -1.000 | FAIL |
| M2K | russell | 122,292 | 2,762 | 0.707 | 0.855 | True | -1.000 | PASS |
| MGC | gold | 95,375 | 2,006 | 0.716 | 0.799 | True | -1.000 | PASS |
| MCL | oil | 79,229 | 1,342 | 0.730 | 0.810 | True | -1.000 | PASS |