# Session isolation implementation

Implement the original PR1 resource controls on the pinned subgroup-stream path. Preserve the existing baseline and optional recovery policies. No new recovery sweep or claimed PACE execution.

## Bandwidth
A relay-owned scheduler gates subgroup stream writes before QUIC. Sessions share byte-based deficit rounds; each session's ready writes retain publisher priority ordering. Charge actual successful bytes, not Objects. Poll blocked writes without holding a global turn or charging bandwidth. Cancelled writes unregister. A shared application-byte rate gate is identical in scheduler-off and DRR comparisons; the existing UDP cap is independent. Control traffic is exempt and reported separately. This schedules application stream bytes, not congestion-control packets.

## Memory
The cache retains whole groups. Enforce a configurable maximum payload per subgroup, reserved before Object creation. Reserve that maximum for each active downstream group and one latest-cache slot per subscription against a session-wide budget. This deliberately conservative accounting gives a payload bound even for groups still growing; it is not an exact physical allocation measurement. Reject over-budget subscription forwarding with TOO_FAR_BEHIND, releasing its work without ending other subscriptions. Count shared groups only once against a global admission reservation budget. Lifetime guards cover Object readers as well as groups. Track reserved/peak bytes, refusals, and releases. These limits exclude QUIC, headers, task/allocator overhead, and OS buffers. Fail closed for unsupported paths when claiming limits.

## Evaluation
Meaningful unit tests cover unequal sizes, multiple streams per session, priorities, blocked writers, cancellation, refunds, cap admission, variable group sizes, shared allocation lifetime, and release. Real QUIC tests compare one versus multiple tracks per session under sustained application congestion, then stalled-client workloads with and without fixed budgets. Keep all client outcomes, repeat conditions, reject timing gaps, retain commands/binary hashes/raw logs. Add patched-policy selection to PACE launcher and verify locally. Update PR2 from the latest Google Doc preserving user edits, with measured outcomes and explicit accounting scope.
