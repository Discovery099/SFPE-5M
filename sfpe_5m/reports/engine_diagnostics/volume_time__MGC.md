# Engine diagnostics  —  `volume_time`  on  **MGC**

- asset class: **commodity**  (family `gold`)
- bars produced: **19,414**
- avg bars per session: **12.334** (spec §11.1 v1.1 band [10, 20]: PASS)
- median source bars per synthetic: **4**
- mean log-return: **-0.000009**
- std log-return: **0.001999**
- source 5-min lag-1 autocorr: **-0.0070**
- synthetic   lag-1 autocorr: **-0.0116**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0116 (src near zero |src_ac1|=0.0070, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 18131, 'session_end': 1259, 'max_bars': 24}**
- **overall verdict: PASS**

![bars per session](volume_time__MGC__bars_per_session.png)