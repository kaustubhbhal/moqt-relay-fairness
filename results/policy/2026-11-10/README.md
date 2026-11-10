# Capped relay and fixed timeout: 20 accepted local runs

These runs compare the same patched relay under an 80 Mbit/s aggregate UDP payload cap, with its subgroup forwarding timeout off or set to three seconds. There are 16 subscribers, either none or eight paused, and five repetitions per condition. Order was shuffled within each repetition with seed 4252. All four conditions use the same binaries, 65,536-byte burst, and client settings.

The accepted matrix completed with no unexpected client failures. Each subscriber was measured for 30 seconds, with a pause from second 5 to 20. All 320 measured wall-clock intervals were 30.000-30.013 seconds. The host was an Apple M2 Pro, 10 reported CPUs, 16 GiB RAM, macOS 15.3.1. All processes ran locally, using four Tokio worker threads each. Source Objects were 16,666 bytes at 30/s, with one subgroup per second. Receive limits were 64 KiB per connection, 32 KiB per stream, and one incoming unidirectional stream.

## What we observed

Each number below is a median of five run-level measurements during seconds 20-30. The healthy cohort is the same upper-half subscriber IDs in all conditions.

| Paused | Timeout | Healthy P99 (ms) | Healthy timely goodput (Mbit/s/client) | Peak RSS (MiB) | UDP egress (Mbit/s) |
| --- | --- | --- | --- | --- | --- |
| 0 | Off | 23.37 | 4.002 | 28.83 | 66.09 |
| 0 | 3 s | 23.28 | 4.003 | 26.17 | 66.09 |
| 8 | Off | 189.62 | 3.860 | 36.92 | 79.85 |
| 8 | 3 s | 10.93 | 4.000 | 23.70 | 33.09 |

Timely goodput means complete Objects arriving within 150 ms of generation. With pauses and no timeout, healthy P99 ranged from 175.42 to 206.17 ms; with the timeout it ranged from 9.52 to 16.06 ms. Observed ranges are not confidence intervals.

The timeout terminated all 40 paused subscriptions in its five mixed runs and no healthy subscriptions. No subscriptions terminated in other conditions. Terminated clients remained in throughput denominators through the end of each planned run. Their recovery goodput is zero and their P99 is undefined. Without the timeout, paused clients received a median 5.776 Mbit/s during recovery, but their timely goodput was zero and median P99 was 14.944 seconds.

This is evidence that catch-up traffic can interfere with healthy clients under the imposed shared bandwidth limit, and that closing stalled subscriptions reduces that interference. It is not evidence of an adaptive scheduler, successful reconnection, or useful recovery for the stalled cohort. The timeout includes source subgroup completion and FIN acknowledgment; it is not a strict memory budget or live-edge measurement. Direct PUBLISH exercises shared downstream fan-out, not upstream SUBSCRIBE deduplication. These are local synthetic-Object tests, not ICE or video-playback results.

The cap counts UDP payload including QUIC overhead, ACK/control traffic, and retransmissions. It excludes IP/Ethernet headers and allows a 64 KiB burst; a short measured interval may therefore slightly exceed 80 Mbit/s. Healthy-only controls can also hit the bucket briefly during bursts despite their lower sustained demand. We establish sustained contention from the near-80 Mbit/s recovery counter rate, not just a nonzero throttle counter.

## Evidence and reproduction

- `schedule.json`: exact run order and conditions.
- `n*/manifest.json`: host, configuration, commands, source and binary hashes, and process outcomes.
- `n*/*.jsonl.gz` and `*.stderr.gz`: compressed measurement logs, without TLS keys.
- `analysis/summary.json` and `.csv`: per-run measurements, pause checks, and terminal events.
- `analysis/grouped/`: run medians, ranges, and explicit undefined-value counts.
- `figures/`: individual-run plots and caption.
- `SHA256SUMS`: archive checksums.

The patch SHA-256 is `c146283dadfe33241302f0f07417010fcb6e64e18d3c8fd5ca787ceb2f49de3e`, applied to upstream revision `3b2b584b47e4a18f3a6bf48dc9a665c736743443`. Build and execution instructions are in [the experiment guide](../../../docs/capped-relay-experiments.md). The accepted command used `caffeinate -dims` followed by `scripts/run_policy_matrix.py --repeats 5 --clients 16 --egress-mbps 80 --timeout-ms 3000 --seed 4252`, with the generated build manifest supplied through `--build-manifest`.

From the repository root, regenerate the saved analysis and figure with:

```bash
python3 scripts/analyze.py results/policy/2026-11-10/n* --out results/policy/2026-11-10/analysis
python3 scripts/summarize_policy.py results/policy/2026-11-10/analysis/summary.json --out results/policy/2026-11-10/analysis/grouped
python3 scripts/plot_policy.py results/policy/2026-11-10/analysis/summary.json --out results/policy/2026-11-10/figures
```

Plotting needs the optional report dependencies. Manifests retain original absolute execution paths as provenance; those paths are not required when rebuilding from the patch. Earlier attempts with timing gaps were excluded as entire batches. Representative diagnostics and the initial incomplete-Object smoke failure are preserved under `results/diagnostics/2026-11-10-policy/`.

Validation: upstream workspace tests passed (711 tests, two ignored), as did Clippy, formatting, and dependency checks. The metrics-enabled relay test run passed (273 tests, one ignored). The project client passed two tests, and the Python analysis passed eight tests. These suites overlap and should not be added together as independent coverage.
