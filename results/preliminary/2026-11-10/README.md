# Preliminary measurements: November 10, 2026

Twenty real-QUIC local runs, five per condition. Relay unchanged at Cloudflare draft-16 commit `3b2b584b47e4a18f3a6bf48dc9a665c736743443`. The workload/runner code was committed as `d7da004`; later documentation-only commits are recorded in individual manifests where applicable.

Host: Apple M2 Pro, 10 reported CPUs, 16 GiB RAM, macOS 15.3.1. All three application processes ran on this shared host over loopback. No imposed egress cap; no PACE run; no DRR or adaptive relay policy.

## Reproduce

```bash
python3 scripts/run_matrix.py --repeats 5 --clients 16 64 --seed 4251
```

Each accepted subscriber runs for 30 seconds. Stalled subscribers pause MoQT processing at second 5 for 15 seconds, then resume for the final 10 seconds. Both cohorts use one incoming unidirectional stream, a 64 KiB connection receive window, and a 32 KiB stream receive window. Source: one track, 16,666-byte Objects at 30/s, subgroup every 30 Objects. Actual target payload rate is 3.99984 Mbit/s.

The matrix schedule is saved in `schedule.json`. Every listed run completed; none was removed from this matrix. Earlier development smoke tests used different configurations and are not part of these statistics. The failed default-concurrency smoke is discussed in `docs/measurement-notes.md`.

## Results during seconds 5-20

Each value is the median of five run-level measurements. P99 concerns the same upper-half client IDs in both conditions, all of which remain healthy.

| Total clients | Paused clients | Peak relay RSS (MiB) | Healthy P99 latency (ms) | Healthy payload goodput (Mbit/s/client) |
| --- | --- | --- | --- | --- |
| 16 | 0 | 25.53 | 12.61 | 4.000 |
| 16 | 8 | 26.28 | 8.95 | 4.000 |
| 64 | 0 | 52.42 | 11.97 | 3.997 |
| 64 | 32 | 47.86 | 11.36 | 4.000 |

No consistent healthy-client degradation or pause-period RSS increase appears in this configuration. P99 varies between runs; dots in the figure show every repetition. These data do not establish statistical equivalence or fairness under congestion.

## Recovery, seconds 20-30

For the previously paused clients, median received goodput is 9.98 Mbit/s (16 clients) or 10.00 Mbit/s (64 clients). Goodput with Object latency at most 150 ms is only 3.82 and 3.13 Mbit/s, respectively. Their P99 latency is 14.76 and 14.84 seconds. High received throughput here includes old backlog, rather than proving useful live delivery.

At 64 clients, median peak relay RSS during recovery is 64.89 MiB with 32 paused clients, versus 55.69 MiB without pauses. Median relay CPU is 128.80% versus 77.72%, where 100% represents one core. These observations motivate measuring recovery costs, but do not isolate buffer ownership or establish harm to other clients.

## Validity checks

- All 20 runs contain all expected ready and complete records, with no client errors.
- Publisher output during seconds 5-20 is 29.93-30.00 Objects/s.
- Actual pause start: 5.0002-5.0026 seconds after subscriber readiness; duration: 15.0002-15.0052 seconds.
- Across 200 paused subscriber instances, UDP receive growth during the pause is 25,239-34,079 bytes (median 33,959), versus roughly 7.5 MB of source payload generated in 15 seconds. ACKs continue; this validates an actual transport-read stall. UDP bytes include protocol overhead.
- Largest within-run subscriber readiness spread is 34.29 ms.
- The single-stream client setting works around a pinned receiver recovery failure and limits generalization. No vendor files were changed.

## Evidence and analysis

Each run directory contains the original `manifest.json` and gzip-compressed publisher/subscriber events, process samples, Prometheus snapshots, and stderr. No TLS keys are included. `SHA256SUMS` covers these raw archive files and the schedule, not subsequently generated figures or analysis.

Recompute the tables:

```bash
python3 scripts/analyze.py results/preliminary/2026-11-10/n*-r* \
  --out results/preliminary/2026-11-10/analysis
```

Generate figures in a Python environment with matplotlib (3.11.2 was used):

```bash
python3 scripts/plot_results.py results/preliminary/2026-11-10 \
  --summary results/preliminary/2026-11-10/analysis/summary.json \
  --out results/preliminary/2026-11-10/figures
```

See `analysis/summary.csv`, `analysis/summary.json`, and `figures/condition-summary.json` for unrounded run-level values, medians, and ranges. Full measurement definitions are in `docs/measurement-notes.md`.
