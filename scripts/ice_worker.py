#!/usr/bin/env python3
"""Four-node ICE orchestration. Requires built binaries and a Slurm allocation."""

import json
import math
import os
import platform
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request

from run_local import sample_process


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def inspect_command(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        return {"command": command, "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "error": str(exc)}


class Worker:
    def __init__(self):
        self.root = Path(__file__).resolve().parents[1]
        self.rank = int(os.environ["SLURM_PROCID"])
        if self.rank not in range(4):
            raise ValueError("Expected four ranks: relay, publisher, two generators")
        self.role = ["relay", "publisher", "subscribers-0", "subscribers-1"][self.rank]
        self.run = Path(os.environ["MOQT_RUN_DIR"]).resolve()
        nodes = (self.run / "nodes.txt").read_text().splitlines()
        if len(nodes) != 4 or len(set(nodes)) != 4:
            raise ValueError("The ICE job must allocate four distinct nodes")
        self.host = nodes[0]
        self.clients = int(os.environ.get("MOQT_CLIENTS", "32"))
        self.stalled = int(os.environ.get("MOQT_STALL_CLIENTS", "0"))
        self.duration = float(os.environ.get("MOQT_DURATION", "60"))
        self.stall_after = float(os.environ.get("MOQT_STALL_AFTER", "15"))
        self.stall_for = float(os.environ.get("MOQT_STALL_FOR", "10"))
        if self.clients < 2 or not 0 <= self.stalled <= self.clients:
            raise ValueError("Need at least two clients and 0 <= stalled <= clients")
        if not all(math.isfinite(value) for value in
                   (self.duration, self.stall_after, self.stall_for)):
            raise ValueError("Duration and stall times must be finite")
        if not 0 < self.duration <= 1200:
            raise ValueError("MOQT_DURATION must be between 0 and 1200 seconds")
        if min(self.stall_after, self.stall_for) < 0:
            raise ValueError("Stall times must be nonnegative")
        if self.stalled and not (
                0 <= self.stall_after < self.stall_after + self.stall_for < self.duration):
            raise ValueError("A positive stall must finish before the run ends")
        self.environment = {
            "RUST_LOG": os.environ.get("RUST_LOG", "warn"),
            "TOKIO_WORKER_THREADS": os.environ.get("TOKIO_WORKER_THREADS", "4"),
        }
        if int(self.environment["TOKIO_WORKER_THREADS"]) < 1:
            raise ValueError("TOKIO_WORKER_THREADS must be positive")
        self.startup_timeout = 90
        self.deadline = time.monotonic() + self.duration + 2 * self.startup_timeout + 60
        self.child = None
        self.handles = []
        self.local = Path(tempfile.mkdtemp(
            prefix=f"moqt-{os.environ['SLURM_JOB_ID']}-{self.rank}-",
            dir=os.environ.get("TMPDIR") or None))
        self.output = self.run / self.role
        self.output.mkdir()
        self.events = (self.local / "worker.jsonl").open("w", buffering=1)
        self.samples = (self.local / "process.jsonl").open("w", buffering=1)
        self.last_sample = 0.0
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def event(self, event, **fields):
        self.events.write(json.dumps({"time_unix": time.time(), "role": self.role,
                                      "event": event, **fields}) + "\n")

    def check(self, check_child=True):
        now = time.monotonic()
        if self.child is not None and now - self.last_sample >= 1:
            sample = sample_process(self.child, self.role)
            if sample is not None:
                self.samples.write(json.dumps(sample) + "\n")
            self.last_sample = now
        failed = sorted(self.run.glob("*.failed.json"))
        if failed:
            raise RuntimeError(f"Another role failed: {failed[0].name}")
        if time.monotonic() > self.deadline:
            raise TimeoutError("Overall worker deadline exceeded")
        if check_child and self.child is not None and self.child.poll() is not None:
            raise RuntimeError(f"{self.role} exited early: {self.child.returncode}")

    def mark(self, name, **values):
        atomic_json(self.run / (name + ".json"), {"time_unix": time.time(), **values})

    def wait_marker(self, name):
        end = time.monotonic() + self.startup_timeout
        while not (self.run / (name + ".json")).exists():
            self.check()
            if time.monotonic() > end:
                raise TimeoutError(f"Timed out waiting for {name}")
            time.sleep(0.2)

    def start(self, command):
        self.event("start", command=command)
        stdout = (self.local / "stdout.jsonl").open("w")
        stderr = (self.local / "stderr.log").open("w")
        self.handles.extend([stdout, stderr])
        environment = {**os.environ, **self.environment}
        self.child = subprocess.Popen(command, cwd=self.root, stdout=stdout,
                                      stderr=stderr, env=environment,
                                      start_new_session=True)

    def metrics(self):
        with self.http.open("http://127.0.0.1:9090/metrics", timeout=2) as response:
            return response.read().decode()

    def metadata(self):
        atomic_json(self.local / "metadata.json", {
            "role": self.role, "rank": self.rank, "hostname": socket.gethostname(),
            "platform": platform.platform(), "python": platform.python_version(),
            "environment": self.environment, "process_sampling_interval_seconds": 1,
            "slurm": {key: value for key, value in os.environ.items()
                      if key.startswith("SLURM_")},
            "configuration": {"clients": self.clients, "stall_clients": self.stalled,
                              "duration": self.duration, "stall_after": self.stall_after,
                              "stall_for": self.stall_for},
            "cpu": inspect_command(["lscpu"]),
            "memory": inspect_command(["free", "-b"]),
            "interfaces": inspect_command(["ip", "-brief", "address"]),
            "routes": inspect_command(["ip", "route"]),
            "clock": inspect_command(["chronyc", "tracking"]),
        })

    def relay(self):
        address = socket.gethostbyname(self.host)
        certs = self.run / "certs"
        binary = self.root / "vendor/moq-rs/target/release/moq-relay-ietf"
        self.start([str(binary), "--bind", f"{address}:4443",
                    "--tls-cert", str(certs / "cert.pem"),
                    "--tls-key", str(certs / "key.pem"),
                    "--metrics-addr", "127.0.0.1:9090",
                    "--coordinator-file", str(self.local / "coordinator.json")])
        end = time.monotonic() + self.startup_timeout
        while True:
            self.check()
            try:
                self.metrics()
                self.mark("relay.ready")
                break
            except (OSError, ValueError):
                if time.monotonic() > end:
                    raise TimeoutError("Relay metrics never became ready; build metrics-prometheus")
                time.sleep(0.2)
        with (self.local / "metrics.jsonl").open("w", buffering=1) as snapshots:
            while True:
                self.check()
                snapshot = self.metrics()
                snapshots.write(json.dumps({"time_unix": time.time(),
                                            "prometheus": snapshot}) + "\n")
                if all((self.run / f"subscribers-{index}.done.json").exists()
                       for index in range(2)):
                    self.mark("stop")
                    break
                time.sleep(1)

    def common(self, mode, duration):
        return [str(self.root / "target/release/moqt-load"), mode,
                "--relay", f"moqt://{self.host}:4443", "--tls-root",
                str(self.run / "certs/cert.pem"), "--namespace", "experiment",
                "--duration", f"{duration:g}"]

    def publisher(self):
        self.wait_marker("relay.ready")
        self.start(self.common("publish", self.duration + self.startup_timeout + 30) +
                   ["--bitrate", "4000000", "--fps", "30", "--group-frames", "30"])
        end = time.monotonic() + self.startup_timeout
        while True:
            self.check()
            if any(event.get("type") == "ready" and event.get("role") == "publisher"
                   for event in self.read_events(allow_partial=True)):
                self.mark("publisher.ready")
                break
            if time.monotonic() > end:
                raise TimeoutError("Publisher did not report accepted-track readiness")
            time.sleep(0.2)
        while not (self.run / "stop.json").exists():
            self.check()
            time.sleep(0.2)

    def subscribers(self):
        self.wait_marker("publisher.ready")
        first_count = (self.clients + 1) // 2
        count = first_count if self.rank == 2 else self.clients - first_count
        offset = 0 if self.rank == 2 else first_count
        stalled = min(count, max(0, self.stalled - offset))
        self.start(self.common("subscribe", self.duration) +
                   ["--clients", str(count), "--client-offset", str(offset),
                    "--stall-clients", str(stalled), "--stall-after", f"{self.stall_after:g}",
                    "--stall-for", f"{self.stall_for:g}"])
        while self.child.poll() is None:
            self.check(check_child=False)
            time.sleep(0.2)
        if self.child.returncode:
            raise RuntimeError(f"Subscriber binary failed: {self.child.returncode}")
        expected = set(range(offset, offset + count))
        ready, complete = set(), set()
        for event in self.read_events():
            if event.get("type") == "client_error":
                raise RuntimeError(f"Subscriber reported failure: {event}")
            if event.get("role") != "subscriber":
                continue
            if event.get("type") == "ready":
                ready.add(event.get("client"))
            elif event.get("type") == "complete":
                complete.add(event.get("client"))
        if ready != expected or complete != expected:
            raise RuntimeError(
                f"Subscriber records mismatch: expected {sorted(expected)}, "
                f"ready {ready}, complete {complete}")
        self.mark(self.role + ".done", clients=count, offset=offset)

    def read_events(self, allow_partial=False):
        with (self.local / "stdout.jsonl").open() as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    if allow_partial and not line.endswith("\n"):
                        continue
                    raise
                if not isinstance(event, dict):
                    raise ValueError("Expected JSON event objects in native stdout")
                yield event

    def cleanup(self):
        if self.child is not None and self.child.poll() is None:
            try:
                os.killpg(self.child.pid, signal.SIGTERM)
                self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.child.pid, signal.SIGKILL)
                self.child.wait(timeout=5)
            except ProcessLookupError:
                pass
        for handle in self.handles:
            handle.close()
        self.events.close()
        self.samples.close()
        shutil.copytree(self.local, self.output, dirs_exist_ok=True)
        # Leave the temporary directory if copying fails, for manual diagnosis.
        shutil.rmtree(self.local)


def interrupted(signum, _frame):
    raise InterruptedError(f"Received signal {signum}")


def main():
    worker = Worker()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        worker.metadata()
        if worker.rank == 0:
            worker.relay()
        elif worker.rank == 1:
            worker.publisher()
        else:
            worker.subscribers()
        worker.event("complete")
    except BaseException as exc:
        worker.event("failed", error=str(exc))
        worker.mark(worker.role + ".failed", error=str(exc))
        raise
    finally:
        # Ignore subsequent termination signals while preserving role logs.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        worker.cleanup()


if __name__ == "__main__":
    main()
