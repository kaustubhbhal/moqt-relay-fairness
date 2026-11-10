# Same-subscription recovery implementation plan

**Goal:** Measure short pauses and let a stalled subscriber resume current media without reconnecting or replacing its subscription.

**Scope:** Extend the existing fixed subgroup lifetime policy. DRR remains unimplemented. Keep the original relay patch and both published datasets reproducible.

**Design:** A new skip action drops expired and queued subgroup forwarding futures for only the affected subscription, resets their streams, and waits for the next fresh subgroup. A subscriber must explicitly supply a positive DELIVERY_TIMEOUT parameter before this action is allowed. The three-second timer is still a local subgroup-observation policy, not a complete implementation of the spec's per-Object header-receipt timer. Draft-16 section 9.2.2.2 permits earlier abandonment when a timeout is specified; section 10.4.3 allows resetting individual subgroup streams without ending the subscription.

1. Preserve timeout termination as the default. Add `Subscribed::with_subgroup_skip(bool)` and `Relay::with_subgroup_skip(bool)`, with CLI `--subgroup-timeout-action skip|terminate`. Test expired writes, blocked stream opening, FIN-ACK waiting, and successful later delivery on the same subscription.
2. Preserve actual wire reset codes through the receiving cache using `ServeError::Reset(u32)`. Abort an incomplete Object explicitly only on a real stream reset; malformed FIN and payload-validation errors remain failures. Test reset at the header and payload boundaries.
3. Add `live-resync` client feature and a variant-client build linked to the patched transport in an isolated checkout. Match relay and load hashes in each run. Default stock builds remain supported.
4. Add client `--delivery-timeout-ms` and `--allow-subgroup-reset`. Continue only on a typed reset with code 2. Log subgroup losses and retain fixed goodput denominators. Log connection/subscription identifiers at readiness and completion; no reconnect path is added.
5. Add recovery analysis: first timely Object, sustained timely delivery, censored recovery, first/final five-second goodput, and observed sequence gaps. Test zero delivery, isolated timely spikes, and interrupted recovery.
6. Smoke-test no pause, short pause, and long pause. Compare capped baseline, terminate, and skip using identical patched clients, permission parameters, cap, and receive settings. Run five repetitions of 0.25, 1, 2, and 4-second pauses plus healthy-only controls; preserve and report failures rather than relabeling them.
7. Run the upstream workspace gate and explicit metrics tests, client checks, and Python analysis checks. Archive accepted raw runs, show every repetition, update the report with benefits and losses, commit and push milestones.

**Acceptance:** Same connection and subscription before/after pause; no unexpected errors; completed Objects remain payload-validated; skip has observable reset/loss outcomes; healthy performance and paused-client recovery are both reported. The test still uses synthetic independent groups, not encoded video dependencies or ICE.
