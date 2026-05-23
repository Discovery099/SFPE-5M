# Engine diagnostics  —  `volume_time`  on  **ES**

- asset class: **equity**  (family `sp500`)
- bars produced: **24,239**
- avg bars per session: **15.400** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **4**
- mean log-return: **0.000010**
- std log-return: **0.002419**
- source 5-min lag-1 autocorr: **-0.0161**
- synthetic   lag-1 autocorr: **-0.0066**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0066 (src near zero |src_ac1|=0.0161, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 24021, 'session_end': 218}**
- **overall verdict: PASS**

![bars per session](volume_time__ES__bars_per_session.png)