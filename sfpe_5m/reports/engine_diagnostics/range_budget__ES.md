# Engine diagnostics  —  `range_budget`  on  **ES**

- asset class: **equity**  (family `sp500`)
- bars produced: **29,997**
- avg bars per session: **18.819** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **3**
- mean log-return: **0.000009**
- std log-return: **0.002193**
- source 5-min lag-1 autocorr: **-0.0161**
- synthetic   lag-1 autocorr: **-0.0096**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0096 (src near zero |src_ac1|=0.0161, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 29234, 'session_end': 761, 'max_bars': 2}**
- **overall verdict: PASS**

![bars per session](range_budget__ES__bars_per_session.png)