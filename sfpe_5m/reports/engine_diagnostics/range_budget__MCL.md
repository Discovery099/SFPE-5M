# Engine diagnostics  —  `range_budget`  on  **MCL**

- asset class: **commodity**  (family `oil`)
- bars produced: **18,766**
- avg bars per session: **15.612** (spec §11.1 v1.1 band [10, 20]: PASS)
- median source bars per synthetic: **3**
- mean log-return: **-0.000055**
- std log-return: **0.004061**
- source 5-min lag-1 autocorr: **-0.0120**
- synthetic   lag-1 autocorr: **-0.0019**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0019 (src near zero |src_ac1|=0.0120, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 18256, 'session_end': 508, 'max_bars': 2}**
- **overall verdict: PASS**

![bars per session](range_budget__MCL__bars_per_session.png)