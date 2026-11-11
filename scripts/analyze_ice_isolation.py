#!/usr/bin/env python3
"""Merge two ICE generators by client ID; latency is opt-in after clock validation."""
import argparse
import copy
import json
from pathlib import Path

from isolation_experiment import read_events, summarize_records


def merge_generators(generators, clients):
    merged, seen = [], set()
    for records in generators:
        ready = [e for e in records if e.get("type") == "ready" and e.get("role") == "subscriber"]
        ids = [e["client"] for e in ready]
        if len(ids) != len(set(ids)) or seen.intersection(ids):
            raise ValueError("duplicate client IDs across or within generators")
        seen.update(ids)
        merged.extend(records)
    if seen != set(range(clients)):
        raise ValueError("combined generators do not cover every expected client ID")
    return merged


def summarize_distributed(records, clients, duration, warmup, tracks, clocks_verified=False):
    analysis_records = records
    if not clocks_verified:
        # Delivery timestamps and duration are local to each receiving host.
        # Publisher-vs-receiver differences are not usable without clock checks.
        analysis_records = copy.deepcopy(records)
        for event in analysis_records:
            if event.get("type") == "object":
                event["latency_ms"] = 0
    result = summarize_records(analysis_records, clients, duration, warmup, tracks)
    result["cross_host_clocks_verified_by_operator"] = clocks_verified
    if not clocks_verified:
        for client in result["clients"]:
            client["p99_latency_ms"] = None
            client["timely_mbps"] = None
        result["healthy_mean_timely_mbps"] = None
    return result


def analyze_run(run, warmup=3, clocks_verified=False):
    run = Path(run)
    if list(run.glob("*.failed.json")) or not (run / "stop.json").exists():
        raise ValueError("all four workers must complete successfully before analysis")
    roles = ["relay", "publisher", "subscribers-0", "subscribers-1"]
    metadata = {role: json.loads((run / role / "metadata.json").read_text()) for role in roles}
    config = metadata["relay"]["configuration"]
    for role in roles:
        worker_events = read_events(run / role / "worker.jsonl")
        if not worker_events or worker_events[-1]["event"] != "complete":
            raise ValueError(f"worker {role} did not complete")
        if metadata[role]["configuration"] != config:
            raise ValueError("worker workload/policy configurations differ")
        if metadata[role]["binaries"]["binary_sha256"] != metadata["relay"]["binaries"]["binary_sha256"]:
            raise ValueError("workers used different binaries")
    groups = [read_events(run / f"subscribers-{i}" / "stdout.jsonl") for i in range(2)]
    records = merge_generators(groups, config["clients"])
    result = summarize_distributed(records, config["clients"], config["duration"], warmup,
                                   config.get("tracks", 1), clocks_verified)
    result["configuration"] = config
    result["binary_sha256"] = metadata["relay"]["binaries"]["binary_sha256"]
    result["run_directory"] = str(run.resolve())
    result["peak_relay_rss_bytes"] = max((x["rss_bytes"] for x in read_events(run / "relay/process.jsonl")), default=None)
    peaks = {}
    for snapshot in read_events(run / "relay/metrics.jsonl"):
        for line in snapshot["prometheus"].splitlines():
            if not line or line.startswith("#"):
                continue
            name, _, raw = line.rpartition(" ")
            try:
                value = float(raw)
            except ValueError:
                continue
            peaks[name] = max(value, peaks.get(name, value))
    result["metric_maxima"] = peaks
    (run / "merged-subscribers.jsonl").write_text("".join(json.dumps(e) + "\n" for e in records))
    (run / "isolation-summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--warmup", type=float, default=3)
    p.add_argument("--clocks-verified", action="store_true",
                   help="operator has checked and recorded sufficiently small publisher/receiver clock uncertainty")
    args = p.parse_args()
    print(json.dumps(analyze_run(args.run, args.warmup, args.clocks_verified), indent=2))


if __name__ == "__main__":
    main()
