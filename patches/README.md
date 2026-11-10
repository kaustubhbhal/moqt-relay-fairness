# Experimental relay patch

`0001-egress-cap-and-subgroup-timeout.patch` applies to the exact vendor revision `3b2b584b47e4a18f3a6bf48dc9a665c736743443`. It adds:

- `--egress-mbps`: one aggregate outgoing UDP-payload token bucket for the relay endpoint.
- `--egress-burst-bytes`: bucket capacity, default 65,536 bytes.
- `--max-subgroup-age-ms`: optional deadline from the relay's observation of a subgroup to its FIN acknowledgment.

The same patched binary supports both the capped baseline (timeout absent) and capped policy (timeout enabled). The default forwarding path remains unchanged when the timeout is absent. The original `vendor/moq-rs` checkout and initial results remain unchanged.

Build with `python3 scripts/build_variant.py`. The script creates a patch-identified checkout under `.local/relay-variants/`, verifies the exact applied diff, builds with the pinned toolchain, and prints the executable and build-manifest paths. It refuses to replace unexpected edits in an existing checkout.

Pass the executable with `scripts/run_local.py --relay-binary PATH --variant-build-manifest BUILD_JSON`, plus the desired cap and timeout flags. Add `--allow-policy-termination` to both compared conditions so an actual `TOO_FAR_BEHIND` response is recorded as an outcome. Other errors still fail the run.

The cap includes all outgoing UDP payload, including encrypted media, QUIC headers, ACKs, control messages, and retransmissions. It excludes IP/Ethernet overhead and does not implement per-connection fairness. No additional packet queue is created by the wrapper. GSO is disabled in both capped conditions.

The timeout is a fixed forwarding-lifetime policy. It does not measure the source live edge and is not a strict memory limit. It also includes time waiting for the source to finish a subgroup: a three-second timeout is inappropriate for a source that deliberately keeps each subgroup open longer than three seconds. The experimental source closes a subgroup approximately every second.

Expiry uses the existing subscription terminal path and stream-reset guards. It does not automatically reconnect the subscriber. Analysis must retain terminated clients with zero further delivered bytes through the planned end of the experiment and report termination separately from healthy-client performance.
