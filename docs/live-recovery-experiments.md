# Returning paused subscribers to current media

The first policy ended a stalled subscription. This variant instead abandons its queued media streams after the same fixed timeout, leaves the subscription open, and waits for a new group. It does not reconnect or create a replacement subscription. DRR is still not implemented.

The original termination policy and original patch remain available. The new patch is cumulative, applied to the same pinned upstream revision in a separate checkout. All comparison conditions use the same new relay and client binaries.

## Policy and protocol scope

Use `--max-subgroup-age-ms 3000 --subgroup-timeout-action skip`. The timer starts when downstream forwarding observes a subgroup, and includes stream opening, forwarding, and final acknowledgment. When it expires, the relay cancels its tracked forwarding and ACK-waiting tasks for that subscription, resets their streams with data reset code 2, and waits for a group newer than the groups it has just abandoned. It never resumes the same discarded group.

The subscriber must supply a positive `DELIVERY_TIMEOUT` parameter; the load client sends it with `--delivery-timeout-ms 3000`. Without that permission, the relay retains the termination behavior. In skip mode the local group deadline uses the smaller of the configured limit and the requested timeout. This is a local group-lifetime policy, **not full implementation of per-Object delivery deadlines measured from incoming Object headers**, nor a strict memory bound. The existing hard ACK-waiter limit can still terminate an overloaded subscription.

Draft-16 section 9.2.2.2 permits publishers to abandon media earlier when a delivery timeout is specified. Section 10.4.3 requires a reset for incomplete subgroup streams and says a subgroup reset does not end the subscription. [Protocol reference](https://www.ietf.org/archive/id/draft-ietf-moq-transport-16.html#section-9.2.2.2).

The patched receiver preserves actual QUIC reset codes through its media cache. With `--allow-subgroup-reset`, the load client records `subgroup_reset` only for reset code 2, discards that subgroup, and continues. Unknown resets, malformed FINs, and payload-validation failures remain failures. If a stream is reset before its first complete Object header, the library has not exposed an application subgroup yet, so that reset may appear only in transport/relay logs. Client reset counts are therefore not complete counts of all discarded streams.

The relay counts resynchronizations and abandoned *tracked work items*. The latter can include pending stream openings and FIN-ACK waits; it is not a count of lost Objects. Completed Objects remain checked against their sequence/timestamp/payload pattern. The synthetic test groups are independent; we have not shown that an encoded-video decoder can recover without waiting for a suitable keyframe.

## Build and run

From the repository root:

```bash
python3 scripts/build_variant.py --patch patches/0002-same-subscription-recovery.patch --build-client
```

The command prints a `build.json` path under `.local/relay-variants/`. Supply that path below:

```bash
caffeinate -dims python3 scripts/run_recovery_matrix.py --build-manifest PATH/TO/build.json --repeats 5
```

On Linux, omit `caffeinate`. Keep the host awake. The duration guard rejects suspension/clock jumps rather than attempting to repair the measurements.

The matrix uses 16 clients, an 80 Mbit/s shared UDP cap, a 64 KiB burst, and the existing 4 Mbit/s source. It compares capped baseline, subscription termination, and skip. In mixed runs eight clients pause for 0.25, 1, 2, or 4 seconds beginning at second 5; each run then observes ten seconds of recovery. Each repetition also has one healthy-only control for each policy. Five repetitions produce 75 runs in seeded shuffled order. Every client sends the same delivery-timeout permission and uses the same reset/termination handling in every condition.

## How we judge recovery

`scripts/analyze_recovery.py RUN_DIR... --out OUTPUT_DIR` measures time from the actual resume event to the first complete Object delivered within 150 ms, and separately to the start of a sustained timely window. The sustained window lasts one second, includes at least 80% of the source's expected frame count, contains no late Objects, and has no arrival gap longer than three frame periods. The reported time is the window's start, confirmed using the following second of data.

Each client's ready and complete records must have the same connection and subscription identifiers, and exactly one connection event. We retain every expected client in first-five-second and final-five-second goodput calculations. A terminated or unrecovered client's recovery time is null, not zero. Conditional recovery medians must always be accompanied by recovered/eligible counts. Received sequence gaps only describe missing IDs between observed endpoints; they are not a complete loss rate over all published Objects.

Healthy-client P99 and timely goodput remain necessary: helping paused clients is not useful if recovery traffic harms everyone else. Report relay memory, stream losses, subscription terminations, and censored recovery alongside latency. These local tests do not establish ICE performance, decoded-video quality, or upstream subscription deduplication.
