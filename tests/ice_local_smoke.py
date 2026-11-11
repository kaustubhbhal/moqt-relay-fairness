#!/usr/bin/env python3
"""Exercise the four ICE worker roles locally, without Slurm or a cluster."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--relay-binary", type=Path)
    parser.add_argument("--load-binary", type=Path)
    parser.add_argument("--build-manifest", type=Path)
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--stall-clients", type=int, default=2)
    parser.add_argument("--duration", type=float, default=8)
    parser.add_argument("--stall-after", type=float, default=2)
    parser.add_argument("--stall-for", type=float, default=3)
    parser.add_argument("--tracks", type=int, default=1)
    parser.add_argument("--extra-track-clients", type=int, default=0)
    parser.add_argument("--application-mbps", type=float)
    parser.add_argument("--scheduler", choices=["fifo", "drr"])
    parser.add_argument("--session-buffer-bytes", type=int)
    parser.add_argument("--global-buffer-bytes", type=int)
    parser.add_argument("--max-group-bytes", type=int)
    parser.add_argument("--receive-window", type=int)
    parser.add_argument("--stream-receive-window", type=int)
    parser.add_argument("--max-uni-streams", type=int)
    parser.add_argument("--allow-policy-termination", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    for port, kind in ((4443, socket.SOCK_DGRAM), (9090, socket.SOCK_STREAM)):
        with socket.socket(socket.AF_INET, kind) as sock:
            sock.bind(("127.0.0.1", port))
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run = repo / "results" / f"ice-local-smoke-{tag}"
    run.mkdir(parents=True, exist_ok=False)
    # Distinct labels exercise the worker's four-role contract; all four
    # processes still run on this ONE machine. This is not an ICE allocation.
    (run / "nodes.txt").write_text("127.0.0.1\nlocal-publisher\nlocal-generator-a\nlocal-generator-b\n")
    subprocess.run([sys.executable, str(repo / "scripts/make_cert.py"),
                    "--out", str(run / "certs"), "--host", "127.0.0.1"], check=True)
    processes, handles = [], []
    try:
        for rank in range(4):
            env = dict(os.environ, SLURM_PROCID=str(rank), SLURM_JOB_ID="local-smoke", MOQT_RUN_DIR=str(run))
            for name in ("relay_binary", "load_binary", "build_manifest", "clients", "stall_clients",
                         "duration", "stall_after", "stall_for", "tracks", "extra_track_clients",
                         "application_mbps", "scheduler", "session_buffer_bytes", "global_buffer_bytes",
                         "max_group_bytes", "receive_window", "stream_receive_window", "max_uni_streams"):
                value = getattr(args, name)
                if value is not None:
                    env["MOQT_" + name.upper()] = str(value.resolve() if isinstance(value, Path) else value)
            if args.allow_policy_termination:
                env["MOQT_ALLOW_POLICY_TERMINATION"] = "1"
            log = (run / f"rank-{rank}.log").open("w")
            handles.append(log)
            processes.append(subprocess.Popen([sys.executable, str(repo / "scripts/ice_worker.py")],
                                               cwd=repo, env=env, stdout=log, stderr=log))
        codes = [proc.wait(timeout=args.duration + 35) for proc in processes]
        if codes != [0, 0, 0, 0]:
            raise RuntimeError(f"worker exit codes {codes}; inspect {run}")
        for role in ("relay", "publisher", "subscribers-0", "subscribers-1"):
            records = [json.loads(line) for line in (run / role / "worker.jsonl").read_text().splitlines()]
            assert records[-1]["event"] == "complete", role
            assert (run / role / "process.jsonl").stat().st_size > 0, role
        assert (run / "stop.json").exists()
        assert not list(run.glob("*.failed.json"))
        subprocess.run([sys.executable, str(repo / "scripts/analyze_ice_isolation.py"),
                        str(run), "--warmup", str(min(2, args.duration / 4))],
                       check=True, stdout=subprocess.DEVNULL)
        summary = json.loads((run / "isolation-summary.json").read_text())
        assert len(summary["clients"]) == args.clients
        assert summary["cross_host_clocks_verified_by_operator"] is False
        print(f"PASS: four local workers, real QUIC, no Slurm/ICE execution. Logs: {run}")
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
