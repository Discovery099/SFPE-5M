# Engine diagnostics  —  `vol_budget`  on  **ES**

- asset class: **equity**  (family `sp500`)
- bars produced: **22,957**
- avg bars per session: **14.585** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **4**
- mean log-return: **0.000012**
- std log-return: **0.002516**
- source 5-min lag-1 autocorr: **-0.0161**
- synthetic   lag-1 autocorr: **+0.0024**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0024 (src near zero |src_ac1|=0.0161, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 21874, 'session_end': 1083}**
- **overall verdict: PASS**

![bars per session](vol_budget__ES__bars_per_session.png)