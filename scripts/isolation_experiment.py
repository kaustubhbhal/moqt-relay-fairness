#!/usr/bin/env python3
"""Repeat controlled session-isolation comparisons; retain all raw outcomes."""
import argparse
from collections import defaultdict
import gzip
import json
import math
from pathlib import Path
import random
import statistics
import subprocess
import sys

from analyze import validate_observation_duration

ROOT = Path(__file__).resolve().parents[1]


def read_events(path):
    path = Path(path)
    if not path.exists() and path.with_suffix(path.suffix + ".gz").exists():
        path = path.with_suffix(path.suffix + ".gz")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def jain(values):
    denominator = len(values) * sum(v * v for v in values)
    return sum(values) ** 2 / denominator if denominator else None


def summarize_records(records, clients, duration, warmup=3.0, source_tracks=1):
    """Aggregate by actual QUIC session/client, never treating tracks as clients."""
    if not 0 <= warmup < duration:
        raise ValueError("warmup must be within the observation duration")
    ready = {e["client"]: e for e in records if e.get("type") == "ready" and e.get("role") == "subscriber"}
    complete = {e["client"]: e for e in records if e.get("type") == "complete" and e.get("role") == "subscriber"}
    if set(ready) != set(range(clients)) or set(complete) != set(ready):
        raise ValueError("missing or unexpected client observations")
    if any(e.get("type") == "client_error" for e in records):
        raise ValueError("client error in run")
    validate_observation_duration(records, duration)
    per_client = []
    for client in range(clients):
        start = ready[client]["timestamp_unix_us"]
        end = start + duration * 1e6
        begin = start + warmup * 1e6
        if ready[client].get("subscription_ids", [ready[client].get("subscription_id")]) != complete[client].get("subscription_ids", [complete[client].get("subscription_id")]):
            raise ValueError("subscription identities changed")
        if ready[client].get("connection_id") != complete[client].get("connection_id"):
            raise ValueError("client reconnected during observation")
        track_ready = [e for e in records if e.get("type") == "track_ready" and e.get("client") == client]
        expected_tracks = ready[client].get("tracks", 1)
        if source_tracks > 1:
            if len(track_ready) != expected_tracks or len({e["subscription_id"] for e in track_ready}) != expected_tracks:
                raise ValueError("incomplete multi-track subscription setup")
            if any(e["connection_id"] != ready[client]["connection_id"] for e in track_ready):
                raise ValueError("tracks split over multiple QUIC sessions")
        objects = [e for e in records if e.get("type") == "object" and e.get("client") == client
                   and begin <= e["received_unix_us"] < end]
        by_track = defaultdict(int)
        seen = set()
        for event in objects:
            key = (event.get("track", "video"), event["seq"])
            if key in seen:
                raise ValueError("duplicate delivered Object within a track")
            seen.add(key)
            if not math.isfinite(event["latency_ms"]) or event["latency_ms"] < 0:
                raise ValueError("invalid latency; check clocks")
            track = event.get("track", "video")
            if source_tracks > 1 and track not in {e["track"] for e in track_ready}:
                raise ValueError("received an unrequested track")
            by_track[track] += event["bytes"]
        seconds = duration - warmup
        total = sum(e["bytes"] for e in objects)
        timely = sum(e["bytes"] for e in objects if 0 <= e["latency_ms"] <= 150)
        terminated = [e for e in records if e.get("type") == "subscription_terminated" and e.get("client") == client]
        per_client.append({"client": client, "cohort": ready[client]["cohort"],
                           "tracks": expected_tracks, "payload_bytes": total,
                           "throughput_mbps": total * 8 / seconds / 1e6,
                           "timely_mbps": timely * 8 / seconds / 1e6,
                           "p99_latency_ms": percentile([e["latency_ms"] for e in objects], .99),
                           "objects": len(objects), "track_payload_bytes": dict(by_track),
                           "terminated_subscriptions": len(terminated),
                           "connection_id": ready[client].get("connection_id")})
    rates = [e["throughput_mbps"] for e in per_client]
    healthy = [e for e in per_client if e["cohort"] == "healthy"]
    return {"clients": per_client, "jain_session_throughput": jain(rates),
            "aggregate_throughput_mbps": sum(rates),
            "healthy_mean_mbps": statistics.mean(e["throughput_mbps"] for e in healthy) if healthy else None,
            "healthy_mean_timely_mbps": statistics.mean(e["timely_mbps"] for e in healthy) if healthy else None,
            "terminated_subscriptions": sum(e["terminated_subscriptions"] for e in per_client),
            "window_seconds": duration - warmup, "warmup_seconds": warmup}


def summarize_run(directory, warmup=3):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["status"] != "complete":
        raise ValueError(f"run is not complete: {directory}")
    config = manifest["config"]
    result = summarize_records(read_events(directory / "subscribers.jsonl"), config["clients"],
                               config["duration"], warmup, config.get("tracks", 1))
    subscribers = read_events(directory / "subscribers.jsonl")
    starts = [e["timestamp_unix_us"] + warmup * 1e6 for e in subscribers if e.get("type") == "ready"]
    ends = [e["timestamp_unix_us"] for e in subscribers if e.get("type") == "complete"]
    common_start, common_end = max(starts), min(ends)
    produced = defaultdict(int)
    for event in read_events(directory / "publisher.jsonl"):
        if event.get("type") == "published" and common_start <= event["sent_unix_us"] < common_end:
            produced[event.get("track", "video")] += 1
    result["publisher_objects_per_second"] = {track: count * 1e6 / (common_end - common_start)
                                                for track, count in produced.items()}
    process = read_events(directory / "process.jsonl")
    result["peak_relay_rss_bytes"] = max((e["rss_bytes"] for e in process if e["role"] == "relay"), default=None)
    metrics = read_events(directory / "metrics.jsonl")
    peaks = {}
    for snapshot in metrics:
        for line in snapshot["text"].splitlines():
            if not line or line.startswith("#"):
                continue
            name, _, value = line.rpartition(" ")
            if any(word in name for word in ("budget", "scheduler", "scheduled", "isolation", "retained", "reservation", "reserved", "admission")):
                try:
                    number = float(value)
                except ValueError:
                    continue
                peaks[name] = max(number, peaks.get(name, number))
    result["resource_metric_maxima"] = peaks
    result["run_directory"] = str(directory)
    result["config"] = config
    (directory / "isolation-summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--analyze", nargs="*", type=Path)
    p.add_argument("--suite", choices=["bandwidth", "memory"], default="bandwidth")
    p.add_argument("--relay-binary", type=Path)
    p.add_argument("--load-binary", type=Path)
    p.add_argument("--variant-build-manifest", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("--seed", type=int, default=4254)
    p.add_argument("--clients", type=int, default=4)
    p.add_argument("--tracks", type=int)
    p.add_argument("--extra-track-clients", type=int)
    p.add_argument("--track-bitrates")
    p.add_argument("--track-priorities")
    p.add_argument("--bitrate", type=int, default=4_000_000)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--duration", type=float, default=15)
    p.add_argument("--warmup", type=float, default=3)
    p.add_argument("--application-mbps", type=float)
    p.add_argument("--session-buffer-bytes", type=int, default=2_097_152)
    p.add_argument("--global-buffer-bytes", type=int, default=8_388_608)
    p.add_argument("--max-group-bytes", type=int, default=524_288)
    p.add_argument("--stall-clients", type=int)
    p.add_argument("--stall-after", type=float, default=3)
    p.add_argument("--stall-for", type=float, default=6)
    p.add_argument("--receive-window", type=int)
    p.add_argument("--stream-receive-window", type=int)
    p.add_argument("--max-uni-streams", type=int)
    args = p.parse_args()
    if args.analyze is not None:
        print(json.dumps([summarize_run(path, args.warmup) for path in args.analyze], indent=2))
        return
    if not args.relay_binary or not args.load_binary or not args.out:
        p.error("running requires relay-binary, load-binary, and out")
    if args.repeats < 1 or not 0 <= args.warmup < args.duration:
        p.error("positive repeats and warmup below duration required")
    args.out.mkdir(parents=True, exist_ok=False)
    bandwidth = args.suite == "bandwidth"
    tracks = args.tracks if args.tracks is not None else (4 if bandwidth else 1)
    extra = args.extra_track_clients if args.extra_track_clients is not None else (1 if bandwidth else 0)
    stalls = args.stall_clients if args.stall_clients is not None else (0 if bandwidth else 1)
    app_rate = args.application_mbps if args.application_mbps is not None else (12 if bandwidth else 64)
    receive = args.receive_window if args.receive_window is not None else (8_388_608 if bandwidth else 65_536)
    stream_receive = args.stream_receive_window if args.stream_receive_window is not None else (2_097_152 if bandwidth else 32_768)
    streams = args.max_uni_streams if args.max_uni_streams is not None else (64 if bandwidth else 1)
    policies = ["baseline", "drr"] if bandwidth else ["baseline", "bounded"]
    rng = random.Random(args.seed)
    schedule = []
    for rep in range(1, args.repeats + 1):
        order = policies.copy()
        rng.shuffle(order)
        schedule.extend((rep, policy) for policy in order)
    (args.out / "schedule.json").write_text(json.dumps({"seed": args.seed, "runs": schedule}, indent=2) + "\n")
    summaries = []
    for rep, policy in schedule:
        out = args.out / f"{policy}-r{rep}"
        cmd = [sys.executable, str(ROOT / "scripts/run_local.py"), "--out", str(out),
               "--label", f"isolation-{args.suite}-{policy}", "--relay-binary", str(args.relay_binary),
               "--load-binary", str(args.load_binary), "--clients", str(args.clients),
               "--tracks", str(tracks), "--extra-track-clients", str(extra),
               "--bitrate", str(args.bitrate), "--fps", str(args.fps),
               "--duration", str(args.duration), "--stall-clients", str(stalls),
               "--stall-after", str(args.stall_after), "--stall-for", str(args.stall_for),
               "--receive-window", str(receive), "--stream-receive-window", str(stream_receive),
               "--max-uni-streams", str(streams), "--application-mbps", str(app_rate),
               "--scheduler", "drr" if policy == "drr" else "fifo",
               "--session-buffer-bytes", str(args.session_buffer_bytes if policy == "bounded" else 0),
               "--global-buffer-bytes", str(args.global_buffer_bytes if not bandwidth else 0),
               "--max-group-bytes", str(args.max_group_bytes), "--allow-policy-termination"]
        for name in ("variant_build_manifest", "track_bitrates", "track_priorities"):
            if getattr(args, name):
                cmd += ["--" + name.replace("_", "-"), str(getattr(args, name))]
        subprocess.run(cmd, check=True)
        result = summarize_run(out, args.warmup)
        result.update(policy=policy, repetition=rep)
        summaries.append(result)
        (args.out / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
        print(json.dumps({"policy": policy, "repetition": rep,
                          "jain": result["jain_session_throughput"],
                          "rates_mbps": [x["throughput_mbps"] for x in result["clients"]],
                          "peak_rss": result["peak_relay_rss_bytes"]}), flush=True)


if __name__ == "__main__":
    main()
