# Same-subscription recovery: 75 accepted local runs

We compare the same patched relay with the forwarding timeout disabled (`baseline`), a three-second timeout that terminates the subscription (`terminate`), and a three-second timeout that resets expired media streams while retaining the subscription (`skip`). DRR is not implemented.

## Experimental setup

All runs use 16 subscribers, an 80 Mbit/s aggregate outgoing UDP payload cap, and a 65,536-byte burst. Eight clients pause for 0.25, 1, 2, or 4 seconds. Each run has five seconds before the pause and ten seconds afterward. Five repetitions of these 12 conditions give 60 runs. Another 15 healthy-only runs give five controls per policy (19 seconds each, with the same nominal recovery interval as the four-second condition). Conditions are shuffled within repetitions using seed 4253.

Hardware: Apple M2 Pro, 10 reported CPUs, 16 GiB RAM, macOS 15.3.1. Relay, publisher, and subscriber generator run on the same machine, with four runtime threads each. Source rate is 30 Objects/s, 16,666 bytes per Object (3.99984 Mbit/s), one new group per second. Every client advertises a 64 KiB connection receive window, 32 KiB stream window, and one incoming unidirectional stream. All conditions use the same reset-aware client, including a positive 3,000 ms delivery timeout permission. Pausing stops MoQT session processing while QUIC continues packet processing and acknowledgments.

The cap includes QUIC overhead and control traffic; it is not a physical-link emulator. The forwarding timer includes opening the stream, forwarding, and FIN acknowledgment, beginning when the downstream forwarder observes the subgroup. It is not the full protocol's per-Object header-receipt deadline or a memory bound. Skip waits for a fresh group after abandoning pending work. These synthetic groups are independently usable; encoded video may need keyframes.

## Results

Each timing entry is the median of five per-run client medians, conditional on recovery. Counts include all 40 paused-client observations in a condition. Timely goodput counts complete payload Objects delivered within 150 ms.

| Pause | Baseline recovered | Baseline recovery (s) | Skip recovered | Skip recovery (s) |
| --- | --- | --- | --- | --- |
| 0.25 s | 40/40 | 0.088421 | 40/40 | 0.080417 |
| 1 s | 40/40 | 1.733180 | 40/40 | 1.692589 |
| 2 s | 40/40 | 4.104113 | 40/40 | 3.978841 |
| 4 s | 30/40 | 8.443194 | 40/40 | 0.024494 |

Four-second pause comparison (medians of five runs):

| Measure | Baseline | Skip | Terminate |
| --- | --- | --- | --- |
| Paused clients recovered | 30/40 | 40/40 | 0/40 |
| Paused subscriptions terminated | 0/40 | 0/40 | 40/40 |
| Healthy recovery P99 (ms) | 173.998 | 48.060 | 12.878 |
| Healthy timely goodput (Mbit/s/client) | 3.9115 | 4.0032 | 3.9998 |
| Paused final-five-second timely goodput (Mbit/s/client) | 1.2999 | 3.9998 | 0 |
| Peak relay RSS during recovery (MiB) | 26.9844 | 23.8125 | 22.3906 |

Skip's four-second recovery run medians range from **0.004642 to 2.104377 seconds**; the slowest individual took **2.39838 seconds**. The low overall median must not hide that variation. The baseline median is conditional on only 30 recoveries; ten clients did not meet the criterion within ten seconds. Terminated clients have undefined recovery times and zero recovery goodput.

Exactly 40 relay resynchronizations and 40 application-visible `Reset(2)` events occurred, all in the four-second skip condition. No subscription reset or termination occurred at shorter pause lengths. All 160 paused-client observations across skip conditions recovered, and none terminated. The termination policy recovered all clients at shorter pauses, but terminated all 40 at four seconds. No healthy client terminated in any condition. Healthy-only P99 medians were 22.991, 22.981, and 22.863 ms for baseline, skip, and terminate respectively.

The two-second case exposes a fixed-threshold limitation: clients spent roughly four seconds catching up without triggering an expired-subgroup reset. The four-second case benefited because it crossed the threshold and discarded stale work. We have evidence of useful same-subscription recovery under this workload, not uniform improvement for every stall or completed cross-session fairness.

## Measurement and validation

Recovery starts at the client's actual `stall_end` event. Sustained timely recovery is the first event-anchored, fully observed one-second window with at least 80% of expected Objects, every received Object within 150 ms, and no delivery or right-edge gap above three frame intervals. Its reported time is the window start, confirmed using the following second. Unrecovered clients are censored at the ten-second observation limit. Conditional times are accompanied by recovered/eligible counts. First-five and final-five goodput use fixed denominators, retaining zeros and terminations.

All 75 runs completed, with exactly five runs in each of 15 conditions. All 1,200 client duration and connection/subscription identity checks passed, and no unexpected client errors occurred. Every run uses identical relay, client, and patch hashes. During recovery the source produced 29.8-30.1 Objects/s; the largest publishing gap was 100.431 ms (143.826 ms across all phases). Temporary host sleep prevention was enabled. Earlier excluded timing-gap runs remain in `results/diagnostics/2026-11-10-policy/`.

Application-visible reset events can undercount transport resets that happen before the first complete Object header, because the receiver has not created a subgroup for the client. The abandoned-work counter counts tracked subgroup work, including unopened streams or FIN acknowledgment waits; it is not an Object loss count. Sequence gaps in the recovery CSV are bounded by observed post-resume IDs and exclude leading/trailing losses; they are not an overall source loss rate.

Code validation passed: upstream default workspace tests (723 passed, two ignored), metrics-enabled relay tests (273 passed, one ignored), Clippy, formatting, and dependency checks. Stock client tests (two), patched client tests (three), and Python tests (18) passed. Upstream suites overlap and must not be added together as independent coverage. Tests include actual QUIC reset delivery, partial Objects, malformed/truncated input, blocked stream opening, and acknowledgment-time expiry.

## Evidence and reproduction

- `schedule.json`: randomized condition order.
- `n*/manifest.json`: host, arguments, revisions, binary hashes, and process outcomes.
- `n*/*.jsonl.gz`, `n*/*.stderr.gz`: compressed raw measurements, excluding TLS keys.
- `analysis/summary.json` and `.csv`: conventional phase/cohort measurements.
- `recovery/recovery.json`, `recovery/recovery-clients.csv`: recovery counts, conditional timings, per-client outcomes and goodput.
- `figures/recovery.png` and `.pdf`: all repetitions, controls, recovery counts and censoring.
- `SHA256SUMS`: checksums of all archive files except itself.

Patch: `cd72e46a1942c33120a3e3c7c8d320f3fc60a12d6c7432393345ca0e350cfc74`, applied directly to upstream `3b2b584b47e4a18f3a6bf48dc9a665c736743443`. Relay SHA-256: `81c0ae2a04bac31bf44c1ec6382802935194fbd8f3f09fbee4f79d6f8d7db492`. Client SHA-256: `b74bc04600abe6595611f5dcfedec3274f6db49e030fa97fe75a67730a8ef4a4`. Client source digest: `b1091a424bbd3ba0fa8790e513c699b6949f67fdfebadb8dfc571c90c777cf1b`.

Build instructions are in [the recovery guide](../../../docs/live-recovery-experiments.md). The accepted matrix command used `caffeinate -dims python3 scripts/run_recovery_matrix.py --build-manifest .local/relay-variants/cd72e46a1942c331/clients/b1091a424bbd3ba0/build.json --repeats 5 --out results/local-recovery-20261110`.

Regenerate from the repository root:

```bash
python3 scripts/analyze.py results/recovery/2026-11-10/n* --out results/recovery/2026-11-10/analysis
python3 scripts/analyze_recovery.py results/recovery/2026-11-10/n* --out results/recovery/2026-11-10/recovery
python3 scripts/plot_recovery.py results/recovery/2026-11-10/recovery/recovery.json --out results/recovery/2026-11-10/figures --summary results/recovery/2026-11-10/analysis/summary.json
```

Plotting uses the optional report dependencies. Original absolute execution paths in manifests are provenance, not prerequisites for rebuilding. No PACE ICE results, encoded-video results, DRR results, or upstream subscription deduplication results are claimed.
