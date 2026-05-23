# Engine diagnostics  —  `dollar_imbalance`  on  **MCL**

- asset class: **commodity**  (family `oil`)
- bars produced: **15,185**
- avg bars per session: **12.633** (spec §11.1 v1.1 band [10, 20]: PASS)
- median source bars per synthetic: **3**
- mean log-return: **-0.000062**
- std log-return: **0.004519**
- source 5-min lag-1 autocorr: **-0.0120**
- synthetic   lag-1 autocorr: **+0.0201**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0201 (src near zero |src_ac1|=0.0120, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 14357, 'session_end': 828}**
- **overall verdict: PASS**

![bars per session](dollar_imbalance__MCL__bars_per_session.png)