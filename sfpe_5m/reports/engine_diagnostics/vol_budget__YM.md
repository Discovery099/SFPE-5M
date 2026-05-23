# Engine diagnostics  —  `vol_budget`  on  **YM**

- asset class: **equity**  (family `dow`)
- bars produced: **22,770**
- avg bars per session: **14.476** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **4**
- mean log-return: **0.000013**
- std log-return: **0.002440**
- source 5-min lag-1 autocorr: **-0.0048**
- synthetic   lag-1 autocorr: **-0.0135**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0135 (src near zero |src_ac1|=0.0048, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 21670, 'session_end': 1100}**
- **overall verdict: PASS**

![bars per session](vol_budget__YM__bars_per_session.png)