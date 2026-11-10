#!/usr/bin/env python3
"""Summarize complete local runs without dropping zero-delivery subscribers."""
import argparse
import csv
import gzip
import json
import math
from pathlib import Path
import statistics


def read_events(path):
    if path.exists():
        opener = open
    else:
        path = path.with_suffix(path.suffix + ".gz")
        opener = gzip.open
    with opener(path, "rt") as f:
        return [json.loads(line) for line in f if line.strip()]


def percentile(values, fraction):
    """Nearest-rank quantile; undefined for an empty sample."""
    return sorted(values)[max(0, math.ceil(fraction * len(values)) - 1)] if values else None


def jain(values):
    denominator = len(values) * sum(x * x for x in values)
    return sum(values) ** 2 / denominator if denominator else None


def metric_value(text, name):
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == name:
            return float(fields[1])
    return None


def validate_observation_duration(records, expected_seconds, tolerance_seconds=0.5):
    """Reject suspension/clock jumps that invalidate wall-clock phase bins."""
    ready = {e["client"]: e["timestamp_unix_us"] for e in records if e.get("type") == "ready"}
    complete = {e["client"]: e["timestamp_unix_us"] for e in records if e.get("type") == "complete"}
    if not ready or set(ready) != set(complete):
        raise ValueError("missing ready/completion timestamps")
    for client, start in ready.items():
        elapsed = (complete[client] - start) / 1e6
        if abs(elapsed - expected_seconds) > tolerance_seconds:
            raise ValueError(f"client {client}: wall-clock observation {elapsed:.3f}s differs from planned {expected_seconds}s; possible host suspension or clock jump")


def egress_measurements(snapshots):
    points = []
    for event in snapshots:
        count = metric_value(event["text"], "moq_relay_egress_udp_bytes_total")
        if count is not None:
            points.append((event["timestamp_unix_us"], count))
    rate = None
    if len(points) >= 2 and points[-1][0] > points[0][0]:
        rate = (points[-1][1] - points[0][1]) * 8 / (points[-1][0] - points[0][0])
    return rate


def summarize_phase(records, ready, ids, start, end, deadline_ms=150):
    if end <= start:
        raise ValueError("empty or reversed measurement phase")
    ids = set(ids)
    delivered = {client: 0 for client in ids}
    timely = {client: 0 for client in ids}
    latency, sequences = [], set()
    for event in records:
        if event.get("type") != "object" or event["client"] not in ids:
            continue
        client = event["client"]
        relative = (event["received_unix_us"] - ready[client]) / 1e6
        if not start <= relative < end:
            continue
        key = (client, event["seq"])
        if key in sequences:
            raise ValueError(f"duplicate received object {key}")
        sequences.add(key)
        value = event["latency_ms"]
        if not math.isfinite(value) or value < 0:
            raise ValueError("invalid latency; check clocks")
        latency.append(value)
        delivered[client] += event["bytes"]
        if value <= deadline_ms:
            timely[client] += event["bytes"]
    rates = [b * 8 / (end - start) / 1e6 for b in delivered.values()]
    timely_rates = [b * 8 / (end - start) / 1e6 for b in timely.values()]
    return {"clients": len(ids), "objects": len(latency), "zero_delivery_clients": sum(b == 0 for b in delivered.values()),
            "latency_median_ms": statistics.median(latency) if latency else None,
            "latency_p99_ms": percentile(latency, .99),
            "mean_client_goodput_mbps": statistics.mean(rates) if rates else None,
            "mean_client_timely_goodput_mbps": statistics.mean(timely_rates) if timely_rates else None,
            "jain_goodput": jain(rates), "deadline_ms": deadline_ms,
            "late_object_fraction": sum(v > deadline_ms for v in latency) / len(latency) if latency else None}


def summarize_run(path, deadline_ms=150):
    manifest = json.loads((path / "manifest.json").read_text())
    if manifest["status"] != "complete":
        raise ValueError(f"{path}: run is {manifest['status']}; do not silently include failed runs")
    config = manifest["config"]
    if config["stall_clients"] > config["clients"] // 2:
        raise ValueError("fixed upper-half healthy comparison requires at most half the clients stalled")
    records = read_events(path / "subscribers.jsonl")
    validate_observation_duration(records, config["duration"])
    expected = set(range(config["clients"]))
    ready_records = [e for e in records if e.get("type") == "ready"]
    ready = {e["client"]: e["timestamp_unix_us"] for e in ready_records}
    completed = {e["client"] for e in records if e.get("type") == "complete"}
    terminated = {e["client"]: e for e in records if e.get("type") == "subscription_terminated"}
    if any(e.get("status_code") != 6 for e in terminated.values()):
        raise ValueError("only an observed TOO_FAR_BEHIND is an allowed policy outcome")
    if set(ready) != expected or completed != expected:
        raise ValueError(f"{path}: missing ready or complete records")
    if any(e.get("type") == "client_error" for e in records):
        raise ValueError(f"{path}: client errors present")
    phases = {"pre_stall": (min(2, config["stall_after"] / 2), config["stall_after"]),
              "stall": (config["stall_after"], config["stall_after"] + config["stall_for"]),
              "recovery": (config["stall_after"] + config["stall_for"], config["duration"])}
    # Keep the SAME upper-half IDs in both 0%-stall and 50%-stall runs.
    groups = {"comparison_healthy": set(range(config["clients"] // 2, config["clients"])),
              "all": expected}
    if config["stall_clients"]:
        groups["stalled"] = set(range(config["stall_clients"]))
    process_all = read_events(path / "process.jsonl")
    process = [e for e in process_all if e["role"] == "relay"]
    published = [e for e in read_events(path / "publisher.jsonl") if e.get("type") == "published"]
    metrics = read_events(path / "metrics.jsonl")
    anchor = statistics.median(ready.values())
    rows = []
    for phase, (start, end) in phases.items():
        samples = [s for s in process if start <= (s["timestamp_unix_us"] - anchor) / 1e6 < end]
        rss = [s["rss_bytes"] / 1024 ** 2 for s in samples]
        cpu = None
        if len(samples) > 1:
            wall = (samples[-1]["timestamp_unix_us"] - samples[0]["timestamp_unix_us"]) / 1e6
            cpu = 100 * (samples[-1]["cpu_seconds"] - samples[0]["cpu_seconds"]) / wall
        source = [e for e in published if start <= (e["sent_unix_us"] - anchor) / 1e6 < end]
        phase_metrics = [e for e in metrics if start <= (e["timestamp_unix_us"] - anchor) / 1e6 < end]
        rate = egress_measurements(phase_metrics)
        role_cpu = {}
        for role in ("publisher", "subscribers"):
            points = [e for e in process_all if e["role"] == role and start <= (e["timestamp_unix_us"] - anchor) / 1e6 < end]
            role_cpu[role + "_cpu_percent_one_core"] = (100 * (points[-1]["cpu_seconds"] - points[0]["cpu_seconds"]) /
                                                       ((points[-1]["timestamp_unix_us"] - points[0]["timestamp_unix_us"]) / 1e6)) if len(points) > 1 else None
        for cohort, ids in groups.items():
            row = {"run": path.name, "total_clients": config["clients"],
                   "stall_clients": config["stall_clients"], "phase": phase, "cohort": cohort,
                   "phase_seconds": end - start,
                   "relay_rss_peak_mib": max(rss) if rss else None,
                   "relay_rss_median_mib": statistics.median(rss) if rss else None,
                   "relay_cpu_percent_one_core": cpu,
                   "publisher_actual_objects_per_second": len(source) / (end - start),
                   "publisher_actual_mbps": sum(e["bytes"] for e in source) * 8 / (end - start) / 1e6,
                   "egress_limit_mbps": config.get("egress_mbps"),
                   "max_subgroup_age_ms": config.get("max_subgroup_age_ms"),
                   "subgroup_timeout_action": config.get("subgroup_timeout_action") or ("terminate" if config.get("max_subgroup_age_ms") else "baseline"),
                   "stall_for": config["stall_for"],
                   "measured_udp_egress_mbps": rate,
                   "terminated_clients_total": len(set(terminated) & ids),
                   "termination_fraction_total": len(set(terminated) & ids) / len(ids) if ids else None,
                   **role_cpu}
            row.update(summarize_phase(records, ready, ids, start, end, deadline_ms))
            rows.append(row)
    stats = [e for e in records if e.get("type") == "quic_stats"]
    stall_checks = []
    for client in range(config["stall_clients"]):
        begin = next((e for e in stats if e["client"] == client and e["phase"] == "stall_begin"), None)
        end = next((e for e in stats if e["client"] == client and e["phase"] == "stall_end"), None)
        if begin is None or end is None:
            if client not in terminated:
                raise ValueError(f"client {client}: incomplete pause without a terminal status")
            stall_checks.append({"client": client, "observed_full_stall": False,
                                 "termination_code": terminated[client]["status_code"]})
            continue
        stall_checks.append({"client": client,
                             "udp_rx_bytes_during_stall": end["udp_rx_bytes"] - begin["udp_rx_bytes"],
                             "rx_stream_frames_during_stall": end["rx_stream_frames"] - begin["rx_stream_frames"],
                             "data_blocked_frames_during_stall": end["rx_data_blocked"] - begin["rx_data_blocked"],
                             "stream_data_blocked_frames_during_stall": end["rx_stream_data_blocked"] - begin["rx_stream_data_blocked"],
                             "acks_sent_during_stall": end["tx_acks"] - begin["tx_acks"],
                             "max_data_sent_during_stall": end["tx_max_data"] - begin["tx_max_data"]})
    return {"run": path.name, "rows": rows, "stall_checks": stall_checks,
            "subgroup_reset_events": [e for e in records if e.get("type") == "subgroup_reset"],
            "relay_live_resync_total": max((metric_value(e["text"], "moq_relay_live_resync_total") or 0 for e in metrics), default=0),
            "relay_subgroups_abandoned_total": max((metric_value(e["text"], "moq_relay_subgroups_abandoned_total") or 0 for e in metrics), default=0),
            "termination_events": list(terminated.values()),
            "relay_too_far_behind_total": max((metric_value(e["text"], "moq_relay_too_far_behind_total") or 0 for e in metrics), default=0),
            "ready_spread_ms": (max(ready.values()) - min(ready.values())) / 1000}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("runs", nargs="+", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--deadline-ms", type=float, default=150)
    args = p.parse_args()
    results = [summarize_run(path, args.deadline_ms) for path in args.runs]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    rows = [row for result in results for row in result["rows"]]
    with (args.out / "summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Summarized {len(results)} complete runs in {args.out}")


if __name__ == "__main__":
    main()
