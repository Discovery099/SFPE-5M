# Engine diagnostics  —  `range_budget`  on  **M2K**

- asset class: **equity**  (family `russell`)
- bars produced: **25,916**
- avg bars per session: **16.258** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **3**
- mean log-return: **-0.000012**
- std log-return: **0.003459**
- source 5-min lag-1 autocorr: **-0.0139**
- synthetic   lag-1 autocorr: **-0.0456**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0456 (src near zero |src_ac1|=0.0139, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 24963, 'session_end': 930, 'max_bars': 23}**
- **overall verdict: PASS**

![bars per session](range_budget__M2K__bars_per_session.png)