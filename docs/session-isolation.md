# Session bandwidth and retained-payload isolation

This is the first implementation of the two controls proposed in Progress Report I. The cumulative patch is `patches/0003-session-isolation.patch`, applied to the unchanged `vendor/moq-rs` revision `3b2b584b47e4a18f3a6bf48dc9a665c736743443`. Earlier timeout/recovery experiments remain archived; the comparisons here leave those timeouts disabled.

## Bandwidth policy

`--application-mbps` sets a common application stream-byte budget. `--scheduler fifo` serves ready write requests in arrival order; `--scheduler drr` allocates credits by the actual downstream QUIC session, so requesting more tracks does not create more shares. Both modes use the same rate limiter and 16 KiB burst allowance. This FIFO comparison is an instrumented baseline, not the unmodified upstream binary.

DRR gives each active session a 16 KiB quantum and writes at most 8 KiB per attempt. Credits are charged for bytes actually accepted by QUIC, including subgroup framing. A blocked write consumes no credits or tokens and does not block other ready sessions. A QUIC wakeup makes it eligible again. Within a session, ready streams are selected by subscriber priority, publisher priority, and arrival order. Existing QUIC stream prioritization is retained. This tests application admission fairness, not complete MoQT priority conformance or fairness of retransmissions on the physical link. Control messages bypass the media scheduler.

## What the memory limits mean

`--max-group-bytes` bounds the sum of declared Object payload sizes in one received subgroup. The current workload has one subgroup per one-second group. Admission reserves the maximum before storing that subgroup, not after it has already grown. Oversized groups are rejected.

`--session-buffer-bytes` bounds conservative reservations across **all subscriptions on a session**. Before a subscription retains a track, it reserves one maximum-sized group for the track's latest cache. Each active forwarding task reserves another group. These charges may count the same shared payload more than once, which makes the bound conservative. If a new forwarding task would exceed the session budget, the affected subscription ends with `TOO_FAR_BEHIND`, releasing its forwarding and cache references. An initial subscription that cannot reserve a cache slot is rejected before acceptance. Other subscriptions and connections retain their own state.

`--global-buffer-bytes` bounds reservations for shared subgroup payloads. A subgroup is charged once globally, even if many downstream sessions reference it. Its reservation is released only after the subgroup and its retained Object readers are released. Global rejection can affect everyone using the source; it is a final admission safeguard, not a promise of healthy-client isolation under global exhaustion.

For the preliminary fixed policy, a subgroup reserves 512 KiB, a session can reserve 2 MiB, and the shared pool can reserve 8 MiB. A single-track session therefore fits one cache slot and three forwarding slots. Across multiple tracks, the cache and forwarding slots still compete for that same 2 MiB. The global pool fits sixteen subgroup reservations. Limits of zero disable enforcement while keeping counters available when a maximum group size is configured.

The bound covers the payload references retained by the tested relay application path. It excludes metadata, allocator overhead, QUIC send/receive buffers, and OS socket buffers. It is **not** a 2 MiB bound on total connection memory or an 8 MiB bound on RSS. The pinned Quinn send window has separate 10,000,000-byte outstanding-stream accounting; it is also not a total connection-memory bound. Small process-memory differences should not be interpreted as proof of physical memory savings from reservation counters alone.

The initial implementation supports a standalone relay using explicit live SUBSCRIBE and subgroup streams. Resource-controlled paths reject FETCH, SUBSCRIBE_NAMESPACE, remote relay lookup, and datagram delivery; resource mode also rejects relay announcement. These restrictions prevent unsupported paths from silently bypassing controls. Multi-relay upstream aggregation is not validated by these experiments.

## Reproduce

Build the isolated variant and matching load program:

```bash
python3 scripts/build_variant.py --patch patches/0003-session-isolation.patch \
  --target-dir .local/isolation-target --build-client
```

Use the printed `binary`, `client_binary`, and `manifest_path` values as the three paths below. Builds and runs preserve source and executable hashes.

```bash
python3 scripts/isolation_experiment.py --suite bandwidth --repeats 3 \
  --relay-binary /PATH/TO/moq-relay-ietf --load-binary /PATH/TO/moqt-load \
  --variant-build-manifest /PATH/TO/build.json --out results/bandwidth-comparison
python3 scripts/isolation_experiment.py --suite memory --repeats 3 \
  --relay-binary /PATH/TO/moq-relay-ietf --load-binary /PATH/TO/moqt-load \
  --variant-build-manifest /PATH/TO/build.json --out results/memory-comparison
```

The bandwidth workload has four QUIC sessions: one requests four 4 Mbit/s tracks, the other three request one each. A shared 12 Mbit/s application cap creates contention. The memory workload has four single-track sessions and a 64 Mbit/s cap; one session pauses for six seconds after three seconds. Both memory arms have the same 8 MiB global cap and 512 KiB group bound, so the treatment changes only the 2 MiB session limit. Check that global admission rejections remain zero before interpreting this as an isolated session-budget comparison.

Each run lasts fifteen seconds; throughput uses seconds 3–15 of each client's observation, including zero-delivery time after termination. Peak RSS uses the full run and is sampled approximately once per second. Raw metrics include both current reservations and lifetime high-water marks. Verify publisher rates near 30 Objects/s per track and inspect failed runs before accepting a comparison. The scripts retain terminated clients in the denominator and verify that multiple tracks actually use the same connection.

For a no-contention control use the bandwidth suite with `--application-mbps 64`. For a healthy memory control use the memory suite with `--stall-clients 0`. A demand-limited multi-track client can legitimately receive more bytes in the no-contention control; Jain fairness is meaningful for the equally weighted, backlogged-session comparison, not as an objective to maximize when clients have different demands.

## Validation and next tests

Unit and integration checks cover partial writes, flow-blocked writes, synchronous QUIC wakeups, reservation rejection/release, Object-reader lifetime, shared session budgets, and source-error propagation. The local testbed exercises real QUIC/TLS connections. The PACE worker path accepts the same policies, checks build hashes, and merges both subscriber generators' results; see [the ICE instructions](pace-ice.md). Actual ICE allocation, Linux builds, network reachability, and clock checks remain deployment steps.

The next experiments should increase subscriber count and stall diversity, exercise global exhaustion, vary Object sizes/priorities, and combine DRR with fixed budgets. Dynamic ACK-based budgets, a direct live-edge lag policy, encoded video, and upstream sharing measurements remain future extensions. These are not needed to interpret the initial two controlled comparisons, but they are needed for a broader claim about real media service quality.
