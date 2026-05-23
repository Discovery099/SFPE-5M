# Engine diagnostics  —  `volume_time`  on  **MNQ**

- asset class: **equity**  (family `nasdaq`)
- bars produced: **25,552**
- avg bars per session: **16.234** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **4**
- mean log-return: **0.000013**
- std log-return: **0.002969**
- source 5-min lag-1 autocorr: **-0.0046**
- synthetic   lag-1 autocorr: **-0.0042**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0042 (src near zero |src_ac1|=0.0046, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 24435, 'session_end': 1117}**
- **overall verdict: PASS**

![bars per session](volume_time__MNQ__bars_per_session.png)