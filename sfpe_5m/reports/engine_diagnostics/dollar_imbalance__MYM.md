# Engine diagnostics  —  `dollar_imbalance`  on  **MYM**

- asset class: **equity**  (family `dow`)
- bars produced: **24,849**
- avg bars per session: **15.599** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **2**
- mean log-return: **0.000012**
- std log-return: **0.002283**
- source 5-min lag-1 autocorr: **-0.0085**
- synthetic   lag-1 autocorr: **-0.0095**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0095 (src near zero |src_ac1|=0.0085, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 24254, 'session_end': 595}**
- **overall verdict: PASS**

![bars per session](dollar_imbalance__MYM__bars_per_session.png)