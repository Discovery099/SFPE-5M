# Engine diagnostics  —  `range_budget`  on  **RTY**

- asset class: **equity**  (family `russell`)
- bars produced: **25,874**
- avg bars per session: **16.232** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **3**
- mean log-return: **-0.000012**
- std log-return: **0.003432**
- source 5-min lag-1 autocorr: **-0.0116**
- synthetic   lag-1 autocorr: **-0.0411**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0411 (src near zero |src_ac1|=0.0116, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 24954, 'session_end': 898, 'max_bars': 22}**
- **overall verdict: PASS**

![bars per session](range_budget__RTY__bars_per_session.png)