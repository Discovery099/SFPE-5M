# Engine diagnostics  —  `dollar_imbalance`  on  **YM**

- asset class: **equity**  (family `dow`)
- bars produced: **24,139**
- avg bars per session: **15.153** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **2**
- mean log-return: **0.000013**
- std log-return: **0.002360**
- source 5-min lag-1 autocorr: **-0.0048**
- synthetic   lag-1 autocorr: **-0.0123**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0123 (src near zero |src_ac1|=0.0048, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 23945, 'session_end': 194}**
- **overall verdict: PASS**

![bars per session](dollar_imbalance__YM__bars_per_session.png)