# Engine diagnostics  —  `volume_time`  on  **MES**

- asset class: **equity**  (family `sp500`)
- bars produced: **25,293**
- avg bars per session: **16.069** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **4**
- mean log-return: **0.000010**
- std log-return: **0.002404**
- source 5-min lag-1 autocorr: **-0.0162**
- synthetic   lag-1 autocorr: **-0.0308**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0308 (src near zero |src_ac1|=0.0162, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 24349, 'session_end': 944}**
- **overall verdict: PASS**

![bars per session](volume_time__MES__bars_per_session.png)