# First local experiment

## Question

When some subscribers stop receiving media temporarily, what happens to the stock relay's memory use and to delivery for subscribers that keep receiving normally?

This implements the first evaluation step in Group 16's submitted Progress Report 1. It is a baseline and testbed milestone, not evidence that our proposed scheduler improves fairness.

## Setup

Run a native Cloudflare draft-16 relay, one synthetic publisher, and a load generator with independent native QUIC subscriber sessions. All processes run on one computer over loopback. Begin with small smoke tests, then increase the subscriber count while checking whether the generator keeps up.

The publisher emits one track at 30 objects per second, averaging 4 Mbit/s, with a new subgroup each second. Each object carries a sequence number and generation timestamp. This gives a repeatable media-shaped workload, but does not reproduce real encoded-video burst sizes or decode dependencies. Real-video replay remains a later experiment.

Compare equal total session counts with 0% and 50% temporarily stalled subscribers. Keep a fixed healthy cohort for like-for-like latency comparisons. Stall media-session processing while leaving the QUIC endpoint alive, then resume the same session. Explicit small client receive windows make flow control observable in a short run. Simply delaying reads from the application's cache would not be a valid network-backpressure test because the library drains QUIC into that cache independently.

## Measurements

- Per-object publisher and receiver timestamps, sequence number, payload bytes, client ID, and cohort.
- Per-client connection, ready, stall-start, stall-end, completion, and failure events.
- Relay resident memory (RSS) and process CPU, sampled throughout the experiment.
- Relay Prometheus metrics, including active connections and subscriptions, with raw snapshots retained.
- Run configuration, commands, revisions, host metadata, duration, and exit codes.

Report end-to-end object delivery time from publisher generation to complete receiver read, not relay-only latency. On one machine the clocks are shared; distributed runs need a clock-offset check before comparing timestamps from different nodes. RSS includes transport buffers, allocator overhead, and other process state; it is not a measurement of the shared media cache alone.

Compute latency and payload goodput separately for healthy and stalled cohorts and for the stall and recovery periods. A subscriber that receives no objects must still contribute zero to throughput/fairness calculations; never hide missing deliveries by reporting latency alone. Short runs and one shared machine limit generalization.

## Success for this milestone

The harness reproducibly sends objects through the real relay, shows that the intended clients pause and resume, preserves raw observations, and produces a defensible baseline comparison. A null result is useful: if healthy clients remain unaffected at this load, report that and test a stronger, controlled bottleneck later. Do not infer bandwidth congestion from subscriber count alone.

## Follow-on work

Implement cross-session scheduling and fixed backlog limits only after identifying the actual contention and accounting points. Compare with the unmodified baseline under a controlled relay egress budget. PACE ICE moves publisher, relay, and generators to separate allocated compute nodes; it is a planned validation environment until we actually run there.
