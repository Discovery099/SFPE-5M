# Engine diagnostics  —  `volume_time`  on  **M2K**

- asset class: **equity**  (family `russell`)
- bars produced: **24,842**
- avg bars per session: **15.783** (spec §11.1 v1.1 band [12, 25]: PASS)
- median source bars per synthetic: **4**
- mean log-return: **-0.000014**
- std log-return: **0.003420**
- source 5-min lag-1 autocorr: **-0.0139**
- synthetic   lag-1 autocorr: **-0.0244**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0244 (src near zero |src_ac1|=0.0139, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 23934, 'session_end': 908}**
- **overall verdict: PASS**

![bars per session](volume_time__M2K__bars_per_session.png)