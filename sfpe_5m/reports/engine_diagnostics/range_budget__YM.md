# Engine diagnostics  —  `range_budget`  on  **YM**

- asset class: **equity**  (family `dow`)
- bars produced: **27,056**
- avg bars per session: **16.984** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **3**
- mean log-return: **0.000012**
- std log-return: **0.002228**
- source 5-min lag-1 autocorr: **-0.0048**
- synthetic   lag-1 autocorr: **-0.0154**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0154 (src near zero |src_ac1|=0.0048, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 26255, 'session_end': 784, 'max_bars': 17}**
- **overall verdict: PASS**

![bars per session](range_budget__YM__bars_per_session.png)