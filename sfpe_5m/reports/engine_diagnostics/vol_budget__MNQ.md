# Engine diagnostics  —  `vol_budget`  on  **MNQ**

- asset class: **equity**  (family `nasdaq`)
- bars produced: **23,090**
- avg bars per session: **14.670** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **4**
- mean log-return: **0.000015**
- std log-return: **0.003133**
- source 5-min lag-1 autocorr: **-0.0046**
- synthetic   lag-1 autocorr: **+0.0050**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0050 (src near zero |src_ac1|=0.0046, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 21859, 'session_end': 1231}**
- **overall verdict: PASS**

![bars per session](vol_budget__MNQ__bars_per_session.png)