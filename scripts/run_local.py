#!/usr/bin/env python3
"""Run real MoQT publisher/relay/subscribers on loopback and retain evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import time
import urllib.request

from make_cert import make_cert
from analyze import validate_observation_duration

ROOT = Path(__file__).resolve().parents[1]


def command_output(args):
    if args[0] == "git":
        args = ["git", "-c", "core.fsmonitor=false", *args[1:]]
    try:
        result = subprocess.run(args, capture_output=True, text=True, cwd=ROOT, timeout=10)
    except subprocess.TimeoutExpired:
        return "unavailable: command timed out"
    return result.stdout.strip() if result.returncode == 0 else None


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def events(path):
    if not path.exists():
        return []
    result = []
    for line in path.read_text().splitlines():
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            # A concurrently written final line can be incomplete.
            continue
    return result


def cpu_seconds(value):
    days, sep, tail = value.partition("-")
    if not sep:
        tail, days = days, "0"
    total = 0.0
    for part in tail.split(":"):
        total = total * 60 + float(part)
    return total + int(days) * 86400


def physical_memory_bytes():
    if platform.system() == "Darwin":
        value = command_output(["sysctl", "-n", "hw.memsize"])
        return int(value) if value and value.isdigit() else None
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError):
        return None


def sample_process(proc, role):
    result = subprocess.run(["ps", "-p", str(proc.pid), "-o", "rss=", "-o", "time="],
                            text=True, capture_output=True)
    values = result.stdout.split()
    if result.returncode or len(values) != 2:
        return None
    return {"timestamp_unix_us": time.time_ns() // 1000, "role": role,
            "pid": proc.pid, "rss_bytes": int(values[0]) * 1024,
            "cpu_seconds": cpu_seconds(values[1])}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--clients", type=int, default=16)
    p.add_argument("--stall-clients", type=int, default=0)
    p.add_argument("--duration", type=float, default=30)
    p.add_argument("--stall-after", type=float, default=5)
    p.add_argument("--stall-for", type=float, default=15)
    p.add_argument("--bitrate", type=int, default=4_000_000)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--group-frames", type=int, default=30)
    p.add_argument("--tracks", type=int, default=1)
    p.add_argument("--extra-track-clients", type=int, default=0)
    p.add_argument("--track-bitrates", help="comma-separated per-track bitrates")
    p.add_argument("--track-priorities", help="comma-separated publisher priorities")
    p.add_argument("--application-mbps", type=float)
    p.add_argument("--scheduler", choices=["fifo", "drr"])
    p.add_argument("--session-buffer-bytes", type=int)
    p.add_argument("--global-buffer-bytes", type=int)
    p.add_argument("--max-group-bytes", type=int)
    p.add_argument("--receive-window", type=int, default=65_536)
    p.add_argument("--stream-receive-window", type=int, default=32_768)
    p.add_argument("--max-uni-streams", type=int, default=1)
    p.add_argument("--relay-binary", type=Path)
    p.add_argument("--load-binary", type=Path)
    p.add_argument("--variant-build-manifest", type=Path)
    p.add_argument("--egress-mbps", type=float)
    p.add_argument("--egress-burst-bytes", type=int, default=65536)
    p.add_argument("--max-subgroup-age-ms", type=int)
    p.add_argument("--subgroup-timeout-action", choices=["terminate", "skip"])
    p.add_argument("--delivery-timeout-ms", type=int)
    p.add_argument("--allow-subgroup-reset", action="store_true")
    p.add_argument("--allow-policy-termination", action="store_true")
    p.add_argument("--label", default="baseline")
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    if not 1 <= args.tracks <= 16 or not 0 <= args.extra_track_clients <= args.clients:
        p.error("require 1 <= tracks <= 16 and 0 <= extra-track-clients <= clients")
    if args.application_mbps is not None and not 0 < args.application_mbps < 1e9:
        p.error("application-mbps must be positive and finite")
    for name in ("session_buffer_bytes", "global_buffer_bytes", "max_group_bytes"):
        value = getattr(args, name)
        if value is not None and value < 0:
            p.error(f"{name} cannot be negative")
    if (args.session_buffer_bytes or args.global_buffer_bytes) and not args.max_group_bytes:
        p.error("memory budgets require max-group-bytes > 0")
    if not 0 <= args.stall_clients <= args.clients or args.clients < 1:
        p.error("require clients >= 1 and 0 <= stall-clients <= clients")
    if not 0 < args.stall_after < args.stall_after + args.stall_for < args.duration:
        p.error("require 0 < stall-after < stall-after + stall-for < duration")
    if min(args.bitrate, args.fps, args.group_frames, args.receive_window,
           args.stream_receive_window, args.max_uni_streams) <= 0:
        p.error("workload and window values must be positive")
    if args.egress_mbps is not None and not 0 < args.egress_mbps < 1e9:
        p.error("egress-mbps must be positive, finite, and below 1e9")
    if args.max_subgroup_age_ms is not None and args.max_subgroup_age_ms <= 0:
        p.error("max-subgroup-age-ms must be positive")
    if args.delivery_timeout_ms is not None and args.delivery_timeout_ms <= 0:
        p.error("delivery-timeout-ms must be positive")
    if args.subgroup_timeout_action == "skip" and not (args.max_subgroup_age_ms and args.delivery_timeout_ms and args.allow_subgroup_reset):
        p.error("skip requires a subgroup age, delivery-timeout permission, and reset-aware client")
    if args.egress_mbps is not None and args.egress_burst_bytes < 65536:
        p.error("egress-burst-bytes must be at least 65536")
    relay = (args.relay_binary or ROOT / "vendor/moq-rs/target/release/moq-relay-ietf").resolve()
    load = (args.load_binary or ROOT / "target/release/moqt-load").resolve()
    for executable in (relay, load):
        if not executable.is_file():
            p.error(f"build missing executable first: {executable}")
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = (args.out or ROOT / "results" / f"local-{tag}-{args.label}").resolve()
    out.mkdir(parents=True, exist_ok=False)
    # Keep private keys outside results so selected raw runs can safely be committed.
    certdir = ROOT / ".local" / "certs" / tag
    make_cert(certdir, "127.0.0.1")
    port, metrics_port = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_STREAM)
    relay_url = f"moqt://127.0.0.1:{port}"
    metrics_url = f"http://127.0.0.1:{metrics_port}/metrics"
    common = ["--relay", relay_url, "--tls-root", str(certdir / "cert.pem"),
              "--namespace", f"local-{tag}"]
    commands = {
        "relay": [str(relay), "--bind", f"127.0.0.1:{port}",
                  "--tls-cert", str(certdir / "cert.pem"),
                  "--tls-key", str(certdir / "key.pem"),
                  "--metrics-addr", f"127.0.0.1:{metrics_port}",
                  "--coordinator-file", str(out / "coordinator.json")],
        "publisher": [str(load), "publish", *common, "--duration", str(args.duration + 20),
                      "--bitrate", str(args.bitrate), "--fps", str(args.fps),
                      "--group-frames", str(args.group_frames)],
        "subscribers": [str(load), "subscribe", *common, "--duration", str(args.duration),
                        "--clients", str(args.clients), "--client-offset", "0",
                        "--stall-clients", str(args.stall_clients),
                        "--stall-after", str(args.stall_after), "--stall-for", str(args.stall_for),
                        "--receive-window", str(args.receive_window),
                        "--stream-receive-window", str(args.stream_receive_window),
                        "--max-uni-streams", str(args.max_uni_streams)],
    }
    if args.tracks != 1 or args.extra_track_clients:
        commands["publisher"] += ["--tracks", str(args.tracks)]
        commands["subscribers"] += ["--tracks", str(args.tracks), "--extra-track-clients", str(args.extra_track_clients)]
    for name in ("track_bitrates", "track_priorities"):
        if getattr(args, name):
            commands["publisher"] += ["--" + name.replace("_", "-"), getattr(args, name)]
    for name in ("application_mbps", "scheduler", "session_buffer_bytes", "global_buffer_bytes", "max_group_bytes"):
        if getattr(args, name) is not None:
            commands["relay"] += ["--" + name.replace("_", "-"), str(getattr(args, name))]
    if args.egress_mbps is not None:
        commands["relay"] += ["--egress-mbps", str(args.egress_mbps),
                              "--egress-burst-bytes", str(args.egress_burst_bytes)]
    if args.max_subgroup_age_ms is not None:
        commands["relay"] += ["--max-subgroup-age-ms", str(args.max_subgroup_age_ms)]
    if args.subgroup_timeout_action:
        commands["relay"] += ["--subgroup-timeout-action", args.subgroup_timeout_action]
    if args.delivery_timeout_ms:
        commands["subscribers"] += ["--delivery-timeout-ms", str(args.delivery_timeout_ms)]
    if args.allow_subgroup_reset:
        commands["subscribers"] += ["--allow-subgroup-reset"]
    if args.allow_policy_termination:
        commands["subscribers"] += ["--allow-policy-termination"]
    manifest = {"schema_version": 1, "status": "running", "created_utc": tag,
                "config": {**{key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}, "out": str(out)}, "commands": commands,
                "git_commit": command_output(["git", "rev-parse", "HEAD"]),
                "git_status": command_output(["git", "status", "--short"]),
                "upstream_commit": command_output(["git", "-C", "vendor/moq-rs", "rev-parse", "HEAD"]),
                "upstream_status": command_output(["git", "-C", "vendor/moq-rs", "status", "--short"]),
                "host": {"platform": platform.platform(), "machine": platform.machine(),
                         "logical_cpus": os.cpu_count(),
                         "cpu_model": command_output(["sysctl", "-n", "machdep.cpu.brand_string"]) if platform.system() == "Darwin" else command_output(["lscpu"]),
                         "memory_bytes": physical_memory_bytes()},
                "binary_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                                  for name, path in (("relay", relay), ("load", load))},
                "clock": "publisher and subscribers share one host wall clock",
                "sampling_interval_seconds": 0.25,
                "environment": {"RUST_LOG": "warn", "TOKIO_WORKER_THREADS": "4"}}
    if args.variant_build_manifest:
        manifest["variant_build"] = json.loads(args.variant_build_manifest.read_text())
        if manifest["variant_build"]["binary_sha256"] != manifest["binary_sha256"]["relay"]:
            raise ValueError("variant build manifest does not match the selected binary")
        if "client_binary_sha256" in manifest["variant_build"] and manifest["variant_build"]["client_binary_sha256"] != manifest["binary_sha256"]["load"]:
            raise ValueError("variant build manifest does not match the selected load binary")
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    processes, handles = {}, []
    samples = (out / "process.jsonl").open("w")
    metric_file = (out / "metrics.jsonl").open("w")
    handles.extend([samples, metric_file])
    last_sample = last_metrics = 0.0

    def launch(name):
        stdout = (out / f"{name}.jsonl").open("w")
        stderr = (out / f"{name}.stderr").open("w")
        handles.extend([stdout, stderr])
        processes[name] = subprocess.Popen(commands[name], cwd=ROOT, stdout=stdout, stderr=stderr,
                                           env={**os.environ, **manifest["environment"]},
                                           start_new_session=True)

    def tick():
        nonlocal last_sample, last_metrics
        now = time.monotonic()
        if now - last_sample >= 0.25:
            for name, proc in processes.items():
                sample = sample_process(proc, name)
                if sample:
                    samples.write(json.dumps(sample) + "\n")
            samples.flush()
            last_sample = now
        if now - last_metrics >= 1:
            try:
                with urllib.request.urlopen(metrics_url, timeout=0.25) as response:
                    metric_file.write(json.dumps({"timestamp_unix_us": time.time_ns() // 1000,
                                                  "text": response.read().decode()}) + "\n")
                metric_file.flush()
            except OSError:
                pass
            last_metrics = now
        time.sleep(0.03)

    def wait_until(check, label, seconds=15):
        deadline = time.monotonic() + seconds
        while not check():
            for name, proc in processes.items():
                if proc.poll() is not None:
                    raise RuntimeError(f"{name} exited {proc.returncode} while waiting for {label}; see {name}.stderr")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for {label}")
            tick()

    def relay_ready():
        try:
            with urllib.request.urlopen(metrics_url, timeout=0.2) as response:
                return response.status == 200
        except OSError:
            return False

    try:
        launch("relay")
        wait_until(relay_ready, "relay metrics endpoint")
        launch("publisher")
        wait_until(lambda: any(e.get("type") == "ready" for e in events(out / "publisher.jsonl")), "publisher acceptance")
        launch("subscribers")
        wait_until(lambda: len({e.get("client") for e in events(out / "subscribers.jsonl")
                                if e.get("type") == "ready"}) == args.clients, "all subscribers")
        deadline = time.monotonic() + args.duration + 15
        while processes["subscribers"].poll() is None:
            for role in ("relay", "publisher"):
                if processes[role].poll() is not None:
                    raise RuntimeError(f"{role} exited during experiment")
            if time.monotonic() > deadline:
                raise TimeoutError("subscriber generator did not finish")
            tick()
        records = events(out / "subscribers.jsonl")
        if processes["subscribers"].returncode != 0 or any(e.get("type") == "client_error" for e in records):
            raise RuntimeError("subscriber failure; inspect subscribers.jsonl and subscribers.stderr")
        if {e.get("client") for e in records if e.get("type") == "complete"} != set(range(args.clients)):
            raise RuntimeError("missing subscriber completion records")
        validate_observation_duration(records, args.duration)
        manifest["status"] = "complete"
    except BaseException as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        raise
    finally:
        manifest["observed_exit_codes"] = {name: proc.poll() for name, proc in processes.items()}
        manifest["intentional_cleanup"] = [name for name, proc in processes.items() if proc.poll() is None]
        for proc in processes.values():
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in processes.values():
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        manifest["final_exit_codes"] = {name: proc.returncode for name, proc in processes.items()}
        manifest["finished_unix_us"] = time.time_ns() // 1000
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        for handle in handles:
            handle.close()
        print(out, flush=True)


if __name__ == "__main__":
    main()
