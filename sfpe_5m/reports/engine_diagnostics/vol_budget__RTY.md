# Engine diagnostics  —  `vol_budget`  on  **RTY**

- asset class: **equity**  (family `russell`)
- bars produced: **22,754**
- avg bars per session: **14.456** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **4**
- mean log-return: **-0.000014**
- std log-return: **0.003626**
- source 5-min lag-1 autocorr: **-0.0116**
- synthetic   lag-1 autocorr: **-0.0257**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0257 (src near zero |src_ac1|=0.0116, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 21485, 'session_end': 1269}**
- **overall verdict: PASS**

![bars per session](vol_budget__RTY__bars_per_session.png)