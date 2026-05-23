# Engine diagnostics  —  `dollar_imbalance`  on  **MES**

- asset class: **equity**  (family `sp500`)
- bars produced: **24,942**
- avg bars per session: **15.647** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **2**
- mean log-return: **0.000011**
- std log-return: **0.002439**
- source 5-min lag-1 autocorr: **-0.0162**
- synthetic   lag-1 autocorr: **-0.0126**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0126 (src near zero |src_ac1|=0.0162, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 24414, 'session_end': 528}**
- **overall verdict: PASS**

![bars per session](dollar_imbalance__MES__bars_per_session.png)