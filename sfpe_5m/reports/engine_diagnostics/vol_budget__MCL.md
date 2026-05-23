# Engine diagnostics  —  `vol_budget`  on  **MCL**

- asset class: **commodity**  (family `oil`)
- bars produced: **13,678**
- avg bars per session: **11.572** (spec §11.1 v1.1 band [10, 20]: PASS)
- median source bars per synthetic: **5**
- mean log-return: **-0.000070**
- std log-return: **0.004711**
- source 5-min lag-1 autocorr: **-0.0120**
- synthetic   lag-1 autocorr: **-0.0013**
- autocorr gate (Amendment 1): **PASS**  (|synth_ac1|=0.0013 (src near zero |src_ac1|=0.0120, gate<=0.05))
- cross-session bars: **0**
- closing reason breakdown: **{'budget': 12814, 'session_end': 864}**
- **overall verdict: PASS**

![bars per session](vol_budget__MCL__bars_per_session.png)