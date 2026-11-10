# Controlled Relay Egress and Forwarding Timeout

**Goal:** Compare a shared relay egress cap with and without a fixed forwarding timeout, using actual QUIC traffic and retaining terminated clients in the results.

**Architecture:** Keep the original vendor checkout and baseline results unchanged. Apply a reproducible patch to a separate checkout of the same upstream revision. The patch adds a shared UDP socket token bucket and an optional subgroup-forwarding timeout; the load generator and analysis record termination as an outcome.

**Tech stack:** Pinned Rust 1.90, Quinn/Tokio, Cloudflare draft-16, Python standard-library orchestration, matplotlib figures.

**Spec:** This executes the next milestone described in `docs/progress-report-2.md`: controlled capacity followed by a simple backlog-limiting policy. The first policy bounds forwarding lifetime rather than estimating source live-edge lag or claiming a strict memory cap.

## Experimental contract

- Both conditions use the same patched relay, UDP byte-rate cap, burst capacity, transport settings, source workload, and client placement.
- The socket wrapper charges successful outgoing UDP payload bytes. It includes QUIC headers, retransmissions, ACKs, and control messages; it excludes IP/Ethernet overhead.
- No payload copies are queued in the wrapper. No lock is held across an asynchronous write. Artificial `WouldBlock` must arrange a timer wakeup.
- The token bucket is an aggregate capacity limit, not a fair scheduler or a simulated physical link. GSO is disabled for both compared conditions.
- The timeout starts when a subgroup becomes visible to downstream forwarding and includes stream-open waits, payload forwarding, and FIN acknowledgment. It uses one unchanged monotonic deadline.
- Timeout selection lives in the relay. The transport receives an optional forwarding-timeout primitive, defaulting to disabled.
- Expiry terminates the affected subscription with `TOO_FAR_BEHIND`; existing stream-reset guards remain responsible for incomplete streams.
- Client termination is reported only from the actual observed terminal status. Arbitrary reader failures are not relabeled as policy success.
- Terminated subscribers remain in rate denominators until the planned run ends. There is no automatic reconnect in this first policy comparison.
- Initial comparison: 16 subscribers, 4 Mbit/s source, 80 Mbit/s aggregate UDP cap, 64 KiB burst, 0 or 8 paused clients, timeout off or 3 seconds. Confirm cap enforcement and headroom before finalizing repeated experiments.

## Review focus

1. False congestion: verify actual UDP bytes and shaper blocking, rather than inferring it from configuration alone.
2. Cancellation races: keep driving the control stream after a data error long enough to observe the terminal subscription status.
3. Hidden loss: count received data, timely data, termination, and zero-delivery clients together.
4. Deadline restart: FIN-ACK waiting must use the subgroup's original deadline.
5. Baseline contamination: all original files/results remain reproducible; every experimental build records the patch hash.

## Tasks

- [ ] Add and test an aggregate `AsyncUdpSocket` token-bucket wrapper in the relay crate. Test refill, aggregate accounting, failed sends, oversized datagrams, and poller wakeups.
- [ ] Add optional subgroup deadlines to the forwarding path and propagate expiry through existing subscription termination. Test deadline inheritance and disabled behavior.
- [ ] Add relay CLI options `--egress-mbps`, `--egress-burst-bytes`, and `--max-subgroup-age-ms`. Export configuration and byte/termination counters.
- [ ] Save the complete upstream diff under `patches/` with an idempotent isolated-build script; keep `vendor/moq-rs` clean.
- [ ] Extend the load client to record `subscription_terminated` without erasing transport errors or shortening the denominator.
- [ ] Extend local runner/analysis to select the variant, record policy settings and patch identity, and compare termination-aware results.
- [ ] Run upstream required checks and project checks; run uncapped compatibility and capped policy smoke tests.
- [ ] Run repeated conditions only after proving the cap and timeout behave as intended. Preserve all runs and analyze healthy/stalled cohorts separately.
- [ ] Publish measured outcomes and limitations in an addendum, then push the next commits. Do not promise a beneficial policy result before measurement.
