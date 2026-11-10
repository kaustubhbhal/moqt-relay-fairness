# Excluded development runs

These are diagnostics, not performance results. No TLS keys are included.

- `1-local-20261110T175903.926325Z-policy-smoke`: the first timeout smoke test failed two subscribers. A relay stream reset interrupted an Object, and the upstream client exposed `ServeError::Size`. The corrected client records the incomplete Object as lost and waits up to two seconds for a separate, explicit `PUBLISH_DONE(6)`. It still fails on payload corruption or missing terminal status. The subsequent smoke passed with all eight paused clients terminated and no healthy clients terminated.
- `2-n16-s0-t0-r1`: representative invalid run from the first attempted capped matrix. A planned 30-second client observation took about 218 seconds of wall-clock time, with a 188-second gap between source Objects. Although the old runner marked it complete, it is invalid for wall-clock phase analysis. We excluded that entire attempted matrix rather than selecting its better runs.
- `3-n16-s0-t0-r1`: the next attempt, with idle-sleep prevention, was rejected by the new duration guard: its planned 30-second observation took about 84 seconds. The matrix stopped immediately.

These gaps are consistent with host suspension or a large clock discontinuity. The logs do not establish their exact operating-system cause. The runner and analyzer now require each client's ready-to-complete wall-clock duration to match the planned interval within 0.5 seconds. All 20 original archived baseline runs passed this additional check.

The saved manifests preserve their original status and source revision. A historical `complete` field in this diagnostic directory is not a claim of measurement validity. See the separate final results directory for accepted comparisons.
