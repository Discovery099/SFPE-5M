# Engine diagnostics  —  `dollar_imbalance`  on  **MNQ**

- asset class: **equity**  (family `nasdaq`)
- bars produced: **25,186**
- avg bars per session: **15.801** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **2**
- mean log-return: **0.000014**
- std log-return: **0.002981**
- source 5-min lag-1 autocorr: **-0.0046**
- synthetic   lag-1 autocorr: **+0.0333**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0333 (src near zero |src_ac1|=0.0046, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 24306, 'session_end': 880}**
- **overall verdict: PASS**

![bars per session](dollar_imbalance__MNQ__bars_per_session.png)