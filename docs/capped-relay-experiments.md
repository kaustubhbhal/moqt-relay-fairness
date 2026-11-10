# Comparing an egress cap with a fixed subscription timeout

This experiment adds two controls to the pinned relay: a shared limit on outgoing UDP traffic and an optional timeout for forwarding a subgroup. It compares the same patched binary with the timeout off and on. The completed 20-run comparison is archived in [the results directory](../results/policy/2026-11-10/README.md). This document explains how to reproduce and interpret it.

The timeout closes a subscription that cannot finish forwarding a subgroup in time. It is **not** the adaptive scheduler proposed in Progress Report 1: there is no DRR scheduler, adaptive per-client budget, or global memory cap in this patch.

## What is changed

The patch is `patches/0001-egress-cap-and-subgroup-timeout.patch`, based on upstream revision `3b2b584b47e4a18f3a6bf48dc9a665c736743443`. `scripts/build_variant.py` makes a separate checkout under `.local/relay-variants/`, applies the patch, and builds a separate executable. It does not edit `vendor/moq-rs` or replace the original baseline executable.

The build directory name uses the first 16 characters of the patch's SHA-256 hash. Its `build.json` records the complete patch hash, upstream revision, binary hash, compiler version, and build command. If an existing variant checkout no longer matches the patch exactly, the script stops instead of overwriting the edits. Inspect that checkout before deciding how to proceed.

| Flag | Meaning |
| --- | --- |
| `--egress-mbps 80` | Limit aggregate outgoing UDP payload to 80 decimal Mbit/s, or 10,000,000 bytes/s. |
| `--egress-burst-bytes 65536` | Allow up to 65,536 bytes of accumulated burst credit; this is the default and minimum accepted by the experiment CLI. |
| `--max-subgroup-age-ms 3000` | End a subscription if an observed subgroup has not completed forwarding and FIN acknowledgment within 3,000 ms. Leave this flag out to disable the timeout. |
| `--allow-policy-termination` | Tell the load generator to record an observed `TOO_FAR_BEHIND` response as an experimental outcome, rather than reject the run for that response. This is a runner/client flag, not a relay scheduling policy. |

Use `--allow-policy-termination` in **both** compared conditions. It does not turn arbitrary errors into successes: a reset alone is not sufficient evidence of a policy termination. Other unexpected errors still fail the run.

A reset can interrupt an Object before all its bytes arrive. The upstream client then reports a typed `ServeError::Size`. The load generator records this as a delivery error and gives the control stream up to two seconds to supply an explicit `PUBLISH_DONE(6)`, just as for cancellation. It never counts the incomplete Object as delivered. A missing terminal response, payload-checksum failure, or logging error still fails the run.

## What the UDP cap actually measures

The cap is shared across all connections using the relay endpoint. It counts the bytes handed to the UDP socket after QUIC encryption, including QUIC headers, media, ACKs, control messages, and retransmissions. It excludes IP and Ethernet headers. Therefore, an 80 Mbit/s setting is neither 80 Mbit/s of useful media nor an exact physical-link rate.

The implementation uses a token bucket. It starts with a full burst allowance; tokens refill at the configured byte rate. Successful sends consume tokens, while failed sends do not. Over an interval of length `t`, permitted outgoing UDP payload is bounded by the burst allowance plus `rate × t`. This permits short bursts above the average rate. Keep the burst identical in both conditions, and use measured byte-counter differences over time rather than expecting every short sample to equal the configured cap.

The wrapper keeps no extra packet-payload queue. It makes Quinn wait when tokens are unavailable, and disables UDP segmentation offload in both capped conditions so one send cannot hide a large batch. It does not promise FIFO ordering or an equal share for each connection. Differences in which connection becomes writable can still affect service. Very low caps can also delay control traffic and produce transport failures; those failures must remain visible.

## What the timeout actually measures

The timer starts when the downstream forwarder observes a subgroup. One absolute deadline covers opening its stream, waiting for stream/flow-control credit, copying Objects, waiting for the source to finish the subgroup, and waiting for the stream's FIN acknowledgment. The deadline is not restarted between these stages.

On expiry, the existing terminal path reports `TOO_FAR_BEHIND` and closes the affected subscription; existing stream-reset guards clean up pending forwarding. The client does not automatically reconnect. The policy applies to public downstream forwarding; internal relay sessions do not receive this configured timeout.

This is a local fixed forwarding-lifetime limit. It does not measure distance from the source's live edge, bound every retained byte, or implement negotiated `DELIVERY_TIMEOUT` behavior. In particular, time spent waiting for the source to close a subgroup counts against the limit. Our source normally closes one subgroup every 30 frames, approximately once per second. A three-second timeout would be a poor choice for a source that intentionally keeps subgroups open longer than three seconds, even if the receiver is healthy.

## Build the tools

Run from the repository root with Rust 1.90.0, Python 3, and OpenSSL installed. The Python scripts use the standard library. The first build may need to download Cargo dependencies.

```bash
git submodule update --init --recursive
cargo +1.90.0 build --release --locked
python3 scripts/build_variant.py
```

The variant builder enables `metrics-prometheus`, which the runner needs for readiness checks and byte counters. To select the manifest for the current checked-in patch without guessing a directory name:

```bash
VARIANT_TAG=$(python3 -c 'import hashlib; from pathlib import Path; print(hashlib.sha256(Path("patches/0001-egress-cap-and-subgroup-timeout.patch").read_bytes()).hexdigest()[:16])')
BUILD_MANIFEST=".local/relay-variants/$VARIANT_TAG/build.json"
RELAY_BINARY=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["binary"])' "$BUILD_MANIFEST")
```

Keep these commands in the same shell as the experiment commands below. The runner checks that the selected executable's hash matches the build manifest and copies the build information into the run manifest. If the patch changes, rebuild and select its new manifest before running again.

## Run a short check first

These two commands use identical load, cap, burst, and termination handling. Only the timeout differs. Each command prints its own output directory and stops on a failed run.

```bash
python3 scripts/run_local.py \
  --relay-binary "$RELAY_BINARY" --variant-build-manifest "$BUILD_MANIFEST" \
  --clients 4 --stall-clients 2 --duration 12 --stall-after 2 --stall-for 5 \
  --egress-mbps 20 --egress-burst-bytes 65536 \
  --allow-policy-termination --label capped-smoke-no-timeout

python3 scripts/run_local.py \
  --relay-binary "$RELAY_BINARY" --variant-build-manifest "$BUILD_MANIFEST" \
  --clients 4 --stall-clients 2 --duration 12 --stall-after 2 --stall-for 5 \
  --egress-mbps 20 --egress-burst-bytes 65536 --max-subgroup-age-ms 3000 \
  --allow-policy-termination --label capped-smoke-timeout
```

Check the manifests, expected subscriber IDs, process exits, and `subscribers.jsonl` before continuing. A smoke run checks that the setup works; it is not enough evidence for a performance claim.

## Run the repeated comparison

```bash
python3 scripts/run_policy_matrix.py \
  --build-manifest "$BUILD_MANIFEST" \
  --repeats 5 --clients 16 --egress-mbps 80 --timeout-ms 3000 --seed 4252
```

This runs four conditions per repetition, for 20 runs total:

| Stalled clients | Timeout |
| --- | --- |
| None | Disabled |
| None | 3,000 ms |
| Half | Disabled |
| Half | 3,000 ms |

Every run uses the same 80 Mbit/s cap and the default 65,536-byte burst. Each subscriber's intended observation interval lasts 30 seconds: five seconds before the stall, 15 seconds during the stall, and ten seconds afterward. The no-stall controls use the same analysis phases. Conditions are shuffled within each repetition using the recorded seed. The workload itself remains deterministic; the seed controls experiment order, not simulated network randomness.

The client stall pauses MoQT session processing while Quinn continues transport processing and acknowledgments. The shared client settings remain a 64 KiB connection receive window, a 32 KiB stream receive window, and one incoming unidirectional stream at a time. Backpressure appears as those finite limits are reached; a paused client does not immediately stop all UDP traffic. The single-stream setting also limits how broadly these results apply to other clients.

The script writes `schedule.json`, runs each condition, and then invokes the analyzer. It stops on an unexpected failure and keeps the outputs produced so far. Expect at least ten minutes of client measurement, plus startup and cleanup. A custom `--out` path must not already exist.

Keep the host awake for the entire matrix. On macOS, prefix the command with `caffeinate -dims` for temporary sleep prevention. This cannot guarantee that the machine will remain available under every condition. Both the runner and analyzer reject a client's wall-clock observation duration if it differs from the planned interval by more than 0.5 seconds. A laptop suspension or large clock jump otherwise misplaces Objects into analysis phases even when every process exits successfully. Do not merge an interrupted matrix with selected successful runs without reporting that change to the experiment procedure.

At about 4 Mbit/s per subscriber, 16 subscribers request approximately 64 Mbit/s of media before overhead. An 80 Mbit/s cap therefore leaves room for normal traffic while making extra catch-up traffic compete for a finite budget. That reasoning is a workload design choice, not evidence that the cap was saturated: check the measured rate. A separate run at `--egress-mbps 40` would deliberately make all 16 full-rate subscriptions infeasible. Under that condition, do not demand full quality for every subscriber or interpret every termination as accidental. Change one parameter at a time and keep the healthy-only controls.

## Analyze without hiding terminated clients

The matrix writes `analysis/summary.csv` and `analysis/summary.json` in its output directory. To reanalyze individual runs, substitute their printed paths:

```bash
python3 scripts/analyze.py \
  results/local-POLICY-RUN/n16-s8-t0-r1 \
  results/local-POLICY-RUN/n16-s8-t3000-r1 \
  --deadline-ms 150 --out results/capped-selected-analysis
```

Use the same deadline threshold in every comparison. The current default is 150 ms; it is an analysis choice, not a protocol guarantee. The analyzer excludes the first two seconds of the default pre-stall interval, giving phases of 2–5, 5–20, and 20–30 seconds relative to each client's ready event.

Keep these denominators fixed:

- A client's goodput uses the entire planned phase length, including any period after its subscription terminates. Do not divide only by the time that client remained connected.
- Keep every intended client in the cohort. A terminated client contributes no further delivered bytes through the planned end; it is not removed from the average.
- Compare the same upper-half client IDs as the healthy cohort in both healthy-only and mixed runs. Also report all-client results and the stalled cohort where applicable.
- Report terminations alongside latency, timely goodput, and memory. Lower P99 among delivered Objects can simply mean that slow subscriptions were removed.

`late_object_fraction` describes lateness **among received Objects**. It is not a deadline-miss fraction over all expected Objects, because Objects never delivered are absent from that denominator. Timely goodput with the fixed duration and client set captures lost useful delivery more honestly. If nothing is delivered, latency is unavailable rather than zero. Termination counts in each phase row currently describe the whole run, so do not add them across phases or present them as phase-local events; use the timestamped termination records for timing.

The output also includes relay RSS/CPU samples, generator CPU use, achieved source rate, and the measured outgoing UDP rate from the relay counter. Check these together. RSS is process memory, not an isolated cache measurement, and sampled peaks can miss short spikes. Useful goodput is counted at receivers and must not be substituted for the UDP egress counter.

## What would support the next conclusion

Before claiming an improvement, check whether the cap was actually constraining the intended resource, whether the source and generators kept up, and whether the same healthy clients gained timely delivery. Any memory or tail-latency improvement must be shown with its cost in terminated subscriptions and lost useful traffic. A fixed timeout that simply disconnects clients sooner is not evidence that an adaptive scheduler has been implemented or that upstream sharing is preserved under every workload.

These are local QUIC experiments with synthetic Objects on one shared track. They do not decode video, reproduce a WAN, or establish PACE ICE performance. Direct `PUBLISH` exercises downstream fan-out; it does not test deduplication of upstream `SUBSCRIBE` requests. Preserve the raw logs, manifests, patch hash, and exact commands so these limits stay attached to any reported result.
