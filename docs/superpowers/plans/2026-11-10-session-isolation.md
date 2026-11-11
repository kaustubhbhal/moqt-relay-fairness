# Session Isolation Implementation Plan

**Goal:** Implement and evaluate DRR and bounded retained application payload, then revise PR2.
**Architecture:** Relay-owned scheduling through a generic transport write hook; reusable reservation primitives at the cache boundary; per-session policy selection in Producer.
**Spec:** docs/superpowers/specs/2026-11-10-session-isolation.md

## Constraints
Pinned upstream 3b2b584, cumulative isolated patch; no dirty vendor checkout. Fixed limits first. No PACE result without execution. Preserve draft-16 resets and cancellation. Memory reservations are conservative payload bounds, not RSS caps.

## Tasks
- [x] Byte scheduler: deterministic deficit accounting plus async write integration, tests for varying sizes, priority, blocked writes and cancellation; CLI/metrics.
- [x] Reservation accounting: checked admission, RAII release, peak/rejection counters, bounded group creation; session cache/forwarding reservations and global shared-group admission; TOO_FAR_BEHIND propagation.
- [x] Multi-track load: several tracks in one actual QUIC session, per-track events, aggregation by session, mixed demand and stall workloads.
- [x] Reproducible build and focused real-QUIC comparison: identical binaries, cap, source, windows, durations; repeated conditions, no silent failure exclusion.
- [x] PACE worker policy selection and combined-generator analysis readiness; local checks only.
- [x] Review, required upstream/root checks, frequent commits/pushes, report/table/diagram updates and rendered Google Doc verification.

## Review focus
No global-turn retention by a blocked write. No session splitting by track. No memory-release before last payload owner drops. No count limit presented as a byte limit without enforced group size. No per-session isolation or total-memory claim beyond the implemented accounting boundary.
