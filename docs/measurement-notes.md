# Reading the measurements

## Baseline and workload

The relay is the unchanged Cloudflare draft-16 revision `3b2b584b47e4a18f3a6bf48dc9a665c736743443`, built in release mode with `metrics-prometheus`. The experiment client uses the same revision's transport library. It creates one native QUIC connection per subscriber and uses BBR. Each process uses four Tokio worker threads in the recorded local configuration.

The payload rate is requested as 4,000,000 bit/s. Integer Object sizing gives 16,666 bytes per Object at 30 Objects/s, or 3,999,840 bit/s. There are no keyframe bursts in this milestone. The publisher skips missed timer ticks rather than sending artificial catch-up bursts, so the analysis checks the **actual** published Object count and bytes in each interval.

The source uses direct `PUBLISH`; the relay stores that track and serves readers to downstream subscriptions. This is real shared-track fan-out. Upstream pull-subscription aggregation is not measured by this path.

## What a pause means

The harness keeps the same pinned MoQT session future alive but temporarily stops polling it. The transport endpoint continues running. This stops both MoQT media reads and control-message processing for that client; it does not stop QUIC acknowledgements or the entire client process.

The client library otherwise eagerly drains QUIC into an application cache. Delaying only the final application reader would therefore not establish transport backpressure. The harness records cumulative UDP receive bytes, stream-frame counts, flow-control updates, ACK counts, and connection state around the pause. A plateau in media traffic while acknowledgements/keepalives continue is the relevant check. A peer is not required to emit a `DATA_BLOCKED` frame, so its absence is not evidence that media continues flowing.

Both healthy and stalled subscribers use a 65,536-byte connection receive window and a 32,768-byte stream receive window. These are deliberately small experimental settings, not defaults or measurements of typical clients.

## Recovery issue found during setup

An initial four-client smoke test with the library's default incoming-stream allowance failed for both paused clients at resumption with `ServeError::Cancel`; healthy clients completed. Source inspection points to receiver-cache ownership during overlapping subgroup arrivals: the cache keeps the latest subgroup reader, and an older live writer can lose its reader before the application captures it. The receive path treats that cancellation as terminal for the subscription.

We did not suppress the error or count that failed run as a successful measurement. The client now advertises one incoming unidirectional stream (`--max-uni-streams 1`) and applies that setting to both conditions. The short recovery smoke test then passed. This serializes subgroup transport and may influence latency and recovery, so it is a stated limit of the preliminary results. It is a harness configuration change, not a relay fairness improvement. The original failure and its logs are retained locally; testing a receiver fix and higher stream concurrency is future work.

## Statistics

Each subscriber's interval starts at its own accepted-subscription `ready` event. For a 30-second run, analysis uses seconds 2–5 before the pause, 5–20 during it, and 20–30 after resumption. The first two seconds are omitted from the pre-pause statistics. Actual pause markers remain in the raw logs for checking timer error.

For the 0% versus 50% comparison, `comparison_healthy` always uses the upper half of client IDs: 8–15 for 16 clients, and 32–63 for 64. This keeps the compared cohort size fixed. The analyzer rejects conditions with more than half the clients stalled rather than silently mislabeling stalled clients as healthy.

- **Delivery latency:** publisher generation timestamp to the receiver's complete Object read, including transport and application scheduling. It is not relay-only latency, network RTT, or video glass-to-glass delay. P99 uses the nearest-rank definition, calculated within each run and phase.
- **Payload goodput:** received payload bytes divided by the phase duration. Every expected client remains in the denominator, including clients receiving zero bytes. This excludes QUIC headers and control traffic.
- **Timely payload goodput:** received payload bytes whose measured latency is at most 150 ms, divided by phase duration. The threshold is an experiment setting, not a measured human-perception limit or protocol requirement.
- **Late Object fraction:** the fraction of received Objects over that threshold. It is conditional on receipt and does not include Objects never received. We do not call it an overall deadline-miss rate.
- **Recovery goodput:** includes old media arriving after the pause. A high value alone does not establish useful live recovery. Compare timely goodput, Object timestamps, and latency too.
- **Jain fairness:** calculated from per-client received goodput. All-zero delivery produces an undefined value rather than a misleading perfect-fairness score.
- **Relay RSS:** the process's resident memory, including transport buffers, runtime state, and allocator effects. It is not isolated cache usage, logical buffered payload, or a memory-leak measurement. A 250 ms sampler may miss brief peaks.
- **CPU:** cumulative process CPU divided by elapsed time between samples. 100% means one fully occupied CPU core; it is not percent of the whole machine. Publisher and generator measurements help identify a test-driver bottleneck, although low average CPU alone cannot exclude scheduling delays.

Publisher and subscriber timestamps come from one host's wall clock in local runs. Negative latency is rejected. Clock adjustments and unrelated activity can still affect measurements. On ICE, cross-node time comparisons require a measured clock-offset bound; the launcher records available clock information but does not establish synchronization by itself.

## Repetition and interpretation

The fixed matrix uses five runs per condition, shuffled within each repetition with seed 4251. Each run starts a fresh relay. Summarize medians and the observed range across run-level measurements; do not pool all received Objects into one giant sample and treat them as independent trials.

This is a shared laptop over loopback. There is no imposed relay egress bottleneck, no physical client link, no packet-loss experiment, and no playback-quality measurement. Any memory or latency difference is specific to the tested settings. A healthy-client null result means we have not demonstrated harmful interference at that load; it does not prove isolation under congestion. These runs establish a baseline for subsequent policy comparisons.
