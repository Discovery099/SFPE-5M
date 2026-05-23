# Engine diagnostics  —  `dollar_imbalance`  on  **RTY**

- asset class: **equity**  (family `russell`)
- bars produced: **23,405**
- avg bars per session: **14.683** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **2**
- mean log-return: **-0.000014**
- std log-return: **0.003546**
- source 5-min lag-1 autocorr: **-0.0116**
- synthetic   lag-1 autocorr: **-0.0378**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0378 (src near zero |src_ac1|=0.0116, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 23349, 'session_end': 56}**
- **overall verdict: PASS**

![bars per session](dollar_imbalance__RTY__bars_per_session.png)