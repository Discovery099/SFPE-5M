# Engine diagnostics  —  `vol_budget`  on  **MYM**

- asset class: **equity**  (family `dow`)
- bars produced: **22,778**
- avg bars per session: **14.481** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **4**
- mean log-return: **0.000014**
- std log-return: **0.002437**
- source 5-min lag-1 autocorr: **-0.0085**
- synthetic   lag-1 autocorr: **-0.0107**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0107 (src near zero |src_ac1|=0.0085, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 21671, 'session_end': 1107}**
- **overall verdict: PASS**

![bars per session](vol_budget__MYM__bars_per_session.png)