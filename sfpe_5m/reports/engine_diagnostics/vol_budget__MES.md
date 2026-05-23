# Engine diagnostics  —  `vol_budget`  on  **MES**

- asset class: **equity**  (family `sp500`)
- bars produced: **22,969**
- avg bars per session: **14.593** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **4**
- mean log-return: **0.000011**
- std log-return: **0.002518**
- source 5-min lag-1 autocorr: **-0.0162**
- synthetic   lag-1 autocorr: **+0.0005**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0005 (src near zero |src_ac1|=0.0162, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 21865, 'session_end': 1104}**
- **overall verdict: PASS**

![bars per session](vol_budget__MES__bars_per_session.png)