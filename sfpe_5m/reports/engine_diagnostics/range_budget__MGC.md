# Engine diagnostics  —  `range_budget`  on  **MGC**

- asset class: **commodity**  (family `gold`)
- bars produced: **20,616**
- avg bars per session: **12.934** (spec §11.1 v1.1 band [10, 20]: PASS)
- median source bars per synthetic: **3**
- mean log-return: **-0.000008**
- std log-return: **0.001943**
- source 5-min lag-1 autocorr: **-0.0070**
- synthetic   lag-1 autocorr: **+0.0010**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0010 (src near zero |src_ac1|=0.0070, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 19499, 'session_end': 1072, 'max_bars': 45}**
- **overall verdict: PASS**

![bars per session](range_budget__MGC__bars_per_session.png)