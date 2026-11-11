# Initial session-isolation results — November 10, 2026

Twenty completed local runs on an Apple M2 Pro (10 logical CPUs, 16 GiB RAM), macOS 15.3.1 ARM64. UTC timestamps extend into November 11; the experiment date is the operator's America/New_York date. This is not a PACE dataset.

## Matched comparisons

All conditions use the release binaries identified by `build.json`. The cumulative patch SHA-256 is `86c3e297565ee155b05bc8b02b2799806b07c3b75b61377089c8ac6eefdc1da1`. The baseline is the same instrumented relay with FIFO application writes or with session-budget enforcement disabled, not the untouched upstream relay. Prior timeout/skip features are disabled.

| Suite | Conditions | Repeats per condition | Workload |
| --- | --- | --- | --- |
| bandwidth | FIFO / DRR | 3 | Four sessions; one requests four 4 Mbit/s tracks, others one each; 12 Mbit/s application cap |
| memory | no session cap / 2 MiB session cap | 3 | Four one-track sessions; one pauses at 3 s for 6 s; 64 Mbit/s cap |
| bandwidth-control | FIFO / DRR | 2 | Same mixed track requests, 64 Mbit/s cap |
| memory-control | no session cap / 2 MiB session cap | 2 | Four healthy one-track sessions, 64 Mbit/s cap |

Every run lasts 15 seconds. Throughput uses seconds 3–15 per client's observation, counting all tracks and retaining terminated clients in the denominator. Group payload is bounded at 512 KiB throughout. Both memory arms use an 8 MiB global reservation cap, and neither triggers it. Bandwidth tests have no enforced session/global reservation caps. Bandwidth receive windows are 8 MiB/connection and 2 MiB/stream with 64 concurrent streams; memory tests use 64 KiB/connection and 32 KiB/stream with one stream.

Per-suite `schedule.json` preserves policy order. All twenty intended runs completed; none were excluded. All recorded publisher tracks remained within 29.8–30.2 Objects/s over the common measurement interval. Development diagnostics and build failures are not pooled with this release dataset.

## Results

- Contended FIFO median client rates: **6.68, 1.68, 1.68, 1.68 Mbit/s**. DRR: **2.83, 2.98, 2.98, 2.98 Mbit/s**. Median Jain index: **0.6465 → 0.9996**. Aggregate payload: **11.71 → 11.76 Mbit/s**.
- This overload test improves sharing, not live latency: demand is 28 Mbit/s against a 12 Mbit/s cap, queues grow, and measured timely payload (150 ms target) is zero for both policies during seconds 3–15. A combined buffering/media-age policy is still needed.
- In the stalled-client comparison, lifetime per-session peak reservations are **4 → 2 MiB**, global reservation peaks **3.5 → 2 MiB**. The fixed policy ends one stalled subscription per run. Healthy clients retain approximately 4 Mbit/s and per-client P99 latency across all six runs is 9.067–11.635 ms.
- Median full-run sampled relay RSS is **26.859 → 21.906 MiB**, an **18.44%** reduction. Baseline range: 26.781–26.891 MiB; bounded range: 21.047–23.578 MiB. This is not a total-memory cap or a statistical/generalization claim. Reservation counters and RSS cover different things.
- With spare bandwidth both policies deliver 16 Mbit/s to the four-track client and 4 Mbit/s to each other client. In healthy memory controls both policies deliver approximately 4 Mbit/s/client and no subscriptions terminate.

## Files and analysis

Each run retains `manifest.json`, source/client/relay logs, timestamped process and metrics samples, configuration, and `isolation-summary.json`. JSONL records are losslessly gzip-compressed; the analyzer supports these directly. No private TLS keys are included. Original absolute build paths in manifests are provenance, not portable install paths; rebuild using the patch and `scripts/build_variant.py`.

From the repository root:

```bash
python3 scripts/isolation_experiment.py --analyze results/isolation/2026-11-10/memory/baseline-r1
python3 scripts/plot_isolation_results.py
```

Plots require matplotlib and numpy. The report graphs show medians and individual runs, not confidence intervals. Time histories show repetition 1 at approximately one-second sampling; retained high-water counters capture peaks between samples. Session and global reservation peaks in the report come from those counters.

`pace-local-check/` records the final build's four-worker integration check: one relay, one publisher, two subscriber generators, DRR, and a four-track session. This used one Mac and a mocked allocation environment, not Slurm. Worker completion, hashes, merged client IDs, logging, and cleanup passed. Cross-host clock verification remains false, so its analysis intentionally omits cross-host latency claims.

## Validation

- Upstream full default workspace tests: 744 passed, 2 ignored, 0 failed (summed unit/integration/doc-test results).
- Relay tests with `metrics-prometheus`: 280 passed, 1 ignored, 0 failed.
- Upstream `cargo clippy --no-deps`, formatting, and `cargo machete`: passed; no clippy warnings or unused dependencies.
- Root client release tests: 3 passed; root clippy with warnings denied passed during implementation.
- Python experiment/analysis tests: 30 passed; worker shell syntax and Python compilation passed.
- Independent review of the public SUBSCRIBE/subgroup path found no additional blocking defect. Scoped limitations are documented in `docs/session-isolation.md`.
