#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 MoQT Relay Fairness project contributors
# SPDX-License-Identifier: MIT
"""Measure observed pause recovery, retaining terminated and censored clients."""

import argparse
from bisect import bisect_left
from collections import defaultdict
import csv
import importlib.util
import json
import math
from pathlib import Path
import statistics

# Also supports importing this script directly from unittest without sys.path edits.
_spec = importlib.util.spec_from_file_location("moqt_analysis", Path(__file__).with_name("analyze.py"))
analysis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analysis)

RATE_FIELDS = ("first5_payload_mbps", "first5_timely_mbps", "final5_payload_mbps", "final5_timely_mbps")
TIME_FIELDS = ("first_timely_seconds", "sustained_timely_seconds")
NOTES = [
    "Paused clients use their actual stall_end event. Controls use ready + stall_after + stall_for, explicitly labeled nominal_control.",
    "A sustained window starts at a timely complete Object, lasts 1 second, contains at least ceil(0.8*fps) Objects, and every delivered Object is timely. Consecutive arrivals and the final window-edge gap must be <=3/fps seconds.",
    "Only fully observed windows qualify. Terminated clients never count as recovered; their recovery times stay null.",
    "A null recovery time means no qualifying recovery was observed, not zero delay. Conditional medians are reported with recovered/eligible counts and are not survival estimates.",
    "Five-second goodput windows always divide by 5 seconds and retain all clients. Missing delivery contributes zero; actual bytes from censored or later-terminated clients are not erased.",
    "Received sequence gaps count absent IDs strictly between the smallest and largest post-reference received IDs. They exclude unknown leading/trailing losses and are not all-source expected loss.",
    "Run-level cohort goodput means retain all cohort clients. Group statistics summarize these run-level means, rather than pooling Objects.",
    "Healthy phase rows are copied from the existing analyzer and retain its fixed upper-half comparison cohort.",
    "Groups report comparison_healthy and stalled cohorts. Lower-half healthy control clients remain in per-client output but are not a second pooled control cohort.",
]


def finite(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite and numeric")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def sustained_start(objects, start_us, end_us, fps, deadline_ms):
    """Earliest event-anchored full timely window; gaps include the right edge."""
    required = math.ceil(0.8 * fps)
    gap_limit = 3_000_000 / fps
    times = [o["received_unix_us"] for o in objects]
    for index, obj in enumerate(objects):
        start = times[index]
        if start < start_us or obj["latency_ms"] > deadline_ms:
            continue
        end = start + 1_000_000
        if end > end_us:
            break
        stop = bisect_left(times, end, lo=index)
        if stop - index < required:
            continue
        window = objects[index:stop]
        if any(o["latency_ms"] > deadline_ms for o in window):
            continue
        arrivals = times[index:stop] + [end]
        if all(b - a <= gap_limit + 1 for a, b in zip(arrivals, arrivals[1:])):
            return (start - start_us) / 1e6
    return None


def client_measurements(objects, reference_us, planned_end_us, fps, deadline_ms, terminated=False):
    finite(fps, "fps", positive=True)
    finite(deadline_ms, "deadline_ms", positive=True)
    if planned_end_us - reference_us < 5_000_000:
        raise ValueError("need at least five fully observed seconds after the recovery reference")
    ordered = sorted(objects, key=lambda e: e["received_unix_us"])
    seen = set()
    for obj in ordered:
        finite(obj["latency_ms"], "latency_ms")
        if obj["latency_ms"] < 0 or not isinstance(obj["seq"], int) or obj["seq"] < 0:
            raise ValueError("invalid Object latency or sequence")
        if not isinstance(obj["bytes"], int) or obj["bytes"] < 0:
            raise ValueError("invalid Object byte count")
        if obj["seq"] in seen:
            raise ValueError("duplicate received Object sequence")
        seen.add(obj["seq"])
    observed = [o for o in ordered if reference_us <= o["received_unix_us"] < planned_end_us]
    first = next((o for o in observed if o["latency_ms"] <= deadline_ms), None)
    first_time = (first["received_unix_us"] - reference_us) / 1e6 if first else None
    sustained = sustained_start(observed, reference_us, planned_end_us, fps, deadline_ms)
    if terminated:
        first_time = sustained = None
    result = {"first_timely_seconds": first_time, "sustained_timely_seconds": sustained,
              "post_reference_objects": len(observed),
              "post_reference_observation_seconds": (planned_end_us - reference_us) / 1e6}
    for label, begin, end in (("first5", reference_us, reference_us + 5_000_000),
                              ("final5", planned_end_us - 5_000_000, planned_end_us)):
        window = [o for o in observed if begin <= o["received_unix_us"] < end]
        result[label + "_payload_mbps"] = sum(o["bytes"] for o in window) * 8 / 5 / 1e6
        result[label + "_timely_mbps"] = sum(o["bytes"] for o in window if o["latency_ms"] <= deadline_ms) * 8 / 5 / 1e6
    sequences = {o["seq"] for o in observed}
    result["received_sequence_gaps"] = max(sequences) - min(sequences) + 1 - len(sequences) if sequences else 0
    result["first_received_sequence"] = min(sequences) if sequences else None
    result["last_received_sequence"] = max(sequences) if sequences else None
    return result


def unique_event(events, kind, required=True):
    found = [e for e in events if e.get("type") == kind]
    if len(found) > 1 or required and not found:
        raise ValueError(f"expected {'one' if required else 'at most one'} {kind} event")
    return found[0] if found else None


def settings_for(manifest, deadline_ms):
    c = manifest["config"]
    timeout = c.get("max_subgroup_age_ms")
    # Old terminate-only runs predate this CLI flag.
    action = c.get("subgroup_timeout_action", "terminate") if timeout is not None else "off"
    settings = {key: c.get(key) for key in (
        "clients", "stall_clients", "duration", "stall_after", "stall_for", "bitrate",
        "fps", "group_frames", "receive_window", "stream_receive_window", "max_uni_streams",
        "egress_mbps", "egress_burst_bytes",
        "delivery_timeout_ms", "allow_subgroup_reset", "allow_policy_termination",
    )}
    settings.update(subgroup_timeout_action=action, max_subgroup_age_ms=timeout,
                    deadline_ms=deadline_ms,
                    patch_sha256=manifest.get("variant_build", {}).get("patch_sha256"),
                    relay_binary_sha256=manifest.get("binary_sha256", {}).get("relay"),
                    load_binary_sha256=manifest.get("binary_sha256", {}).get("load"))
    return settings


def summarize_run(path, deadline_ms=150):
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text())
    # Reuse completion, duration, allowed status, expected-client and phase checks.
    baseline = analysis.summarize_run(path, deadline_ms)
    c = manifest["config"]
    fps = finite(c["fps"], "fps", positive=True)
    events = analysis.read_events(path / "subscribers.jsonl")
    expected = set(range(c["clients"]))
    if any(e["client"] not in expected for e in events if "client" in e):
        raise ValueError("event names an unexpected client")
    by_client = defaultdict(list)
    for event in events:
        if "client" in event:
            by_client[event["client"]].append(event)
    clients = []
    for client in sorted(expected):
        records = by_client[client]
        ready = unique_event(records, "ready")
        complete = unique_event(records, "complete")
        terminal = unique_event(records, "subscription_terminated", required=False)
        identity_required = bool(c.get("allow_subgroup_reset") or c.get("delivery_timeout_ms"))
        identity_present = any(key in ready or key in complete for key in ("connection_id", "subscription_id"))
        identity_checked = identity_required or identity_present
        if identity_checked:
            unique_event(records, "connection")
            for key in ("connection_id", "subscription_id"):
                if ready.get(key) is None or ready.get(key) != complete.get(key):
                    raise ValueError(f"client {client}: missing or changed {key}; cannot verify same-session recovery")
        if any(e.get("type") == "delivery_error" for e in records) and terminal is None:
            raise ValueError(f"client {client}: delivery failure without terminal status")
        stalled = client < c["stall_clients"]
        resume = unique_event(records, "stall_end", required=False)
        pause = unique_event(records, "stall_begin", required=False)
        planned_end = ready["timestamp_unix_us"] + c["duration"] * 1e6
        if complete["timestamp_unix_us"] < planned_end:
            raise ValueError(f"client {client}: observation ended before the planned analysis window")
        nominal = ready["timestamp_unix_us"] + (c["stall_after"] + c["stall_for"]) * 1e6
        if stalled and resume is None and terminal is None:
            raise ValueError(f"client {client}: missing actual resume without termination")
        if stalled and resume is not None:
            if pause is None or not ready["timestamp_unix_us"] <= pause["timestamp_unix_us"] <= resume["timestamp_unix_us"] < planned_end:
                raise ValueError(f"client {client}: invalid pause/resume timestamps")
            reference = resume["timestamp_unix_us"]
            kind = "actual_stall_end"
        else:
            reference = nominal
            kind = "nominal_terminated_before_resume" if stalled else "nominal_control"
        if terminal and terminal["timestamp_unix_us"] > complete["timestamp_unix_us"]:
            raise ValueError(f"client {client}: termination follows completion")
        resets = [e for e in records if e.get("type") == "subgroup_reset"]
        if any(e.get("code") != 2 for e in resets):
            raise ValueError(f"client {client}: unexpected subgroup reset code")
        cohort = ("comparison_healthy" if client >= c["clients"] // 2 else
                  "stalled" if stalled else "other_healthy")
        row = {"run": path.name, "client": client, "cohort": cohort, "was_paused": stalled,
               "reference_kind": kind, "reference_unix_us": reference,
               "identity_checked": identity_checked, "connection_id": ready.get("connection_id"),
               "subscription_id": ready.get("subscription_id"),
               "terminated": terminal is not None, "termination_code": terminal["status_code"] if terminal else None,
               "subgroup_resets_total": len(resets),
               "subgroup_resets_after_reference": sum(e["timestamp_unix_us"] >= reference for e in resets)}
        row.update(client_measurements([e for e in records if e.get("type") == "object"],
                                       reference, planned_end, fps, deadline_ms, terminal is not None))
        clients.append(row)
    return {"run": path.name, "path": str(path), "settings": settings_for(manifest, deadline_ms),
            "clients": clients, "healthy_phase_rows": [r for r in baseline["rows"] if r["cohort"] == "comparison_healthy"]}


def distribution(values):
    defined = [v for v in values if v is not None]
    return {"total": len(values), "defined": len(defined), "undefined": len(values) - len(defined),
            "median": statistics.median(defined) if defined else None,
            "min": min(defined) if defined else None, "max": max(defined) if defined else None}


def group_runs(runs):
    buckets = defaultdict(list)
    for run in runs:
        for cohort in sorted({c["cohort"] for c in run["clients"]}):
            if cohort not in ("comparison_healthy", "stalled"):
                continue
            clients = [c for c in run["clients"] if c["cohort"] == cohort]
            row = {"run": run["run"], "clients": len(clients),
                   "terminated_clients": sum(c["terminated"] for c in clients),
                   "subgroup_resets_total": sum(c["subgroup_resets_total"] for c in clients),
                   "mean_received_sequence_gaps": statistics.mean(c["received_sequence_gaps"] for c in clients),
                   **{field: statistics.mean(c[field] for c in clients) for field in RATE_FIELDS}}
            for field in TIME_FIELDS:
                times = [c[field] for c in clients]
                row[field + "_conditional"] = distribution(times)
                row[field + "_recovered_clients"] = sum(t is not None for t in times)
                row[field + "_recovered_fraction"] = row[field + "_recovered_clients"] / len(clients)
            row["sustained_censored_clients"] = sum(not c["terminated"] and c["sustained_timely_seconds"] is None for c in clients)
            key = (json.dumps(run["settings"], sort_keys=True), cohort)
            buckets[key].append(row)
    groups = []
    for (settings, cohort), rows in sorted(buckets.items()):
        group = {"settings": json.loads(settings), "cohort": cohort, "runs": len(rows),
                 "client_observations": sum(r["clients"] for r in rows),
                 "terminated_clients": sum(r["terminated_clients"] for r in rows),
                 "sustained_censored_clients": sum(r["sustained_censored_clients"] for r in rows),
                 "subgroup_resets_total": sum(r["subgroup_resets_total"] for r in rows),
                 "metrics": {field: distribution([r[field] for r in rows]) for field in RATE_FIELDS},
                 "run_cohorts": rows}
        group["metrics"]["mean_received_sequence_gaps"] = distribution([r["mean_received_sequence_gaps"] for r in rows])
        for field in TIME_FIELDS:
            group[field + "_recovered_clients"] = sum(r[field + "_recovered_clients"] for r in rows)
            group[field + "_recovered_fraction"] = group[field + "_recovered_clients"] / group["client_observations"]
            group["metrics"][field + "_conditional_run_medians"] = distribution([r[field + "_conditional"]["median"] for r in rows])
        groups.append(group)
    return groups


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--deadline-ms", type=float, default=150)
    args = parser.parse_args()
    try:
        finite(args.deadline_ms, "deadline_ms", positive=True)
        if len({p.resolve() for p in args.runs}) != len(args.runs) or len({p.name for p in args.runs}) != len(args.runs):
            raise ValueError("duplicate run directory/name")
        runs = [summarize_run(p, args.deadline_ms) for p in args.runs]
        result = {"schema_version": 1, "notes": NOTES, "runs": runs, "groups": group_runs(runs)}
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "recovery.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    write_csv(args.out / "recovery-clients.csv", [c for run in runs for c in run["clients"]])
    print(f"Analyzed recovery for {len(runs)} runs in {args.out}")


if __name__ == "__main__":
    main()
