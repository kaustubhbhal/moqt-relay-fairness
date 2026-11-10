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
            env = dict(os.environ, SLURM_PROCID=str(rank), SLURM_JOB_ID="local-smoke",
                       MOQT_RUN_DIR=str(run), MOQT_CLIENTS="4", MOQT_STALL_CLIENTS="2",
                       MOQT_DURATION="8", MOQT_STALL_AFTER="2", MOQT_STALL_FOR="3")
            log = (run / f"rank-{rank}.log").open("w")
            handles.append(log)
            processes.append(subprocess.Popen([sys.executable, str(repo / "scripts/ice_worker.py")],
                                               cwd=repo, env=env, stdout=log, stderr=log))
        codes = [proc.wait(timeout=45) for proc in processes]
        if codes != [0, 0, 0, 0]:
            raise RuntimeError(f"worker exit codes {codes}; inspect {run}")
        for role in ("relay", "publisher", "subscribers-0", "subscribers-1"):
            records = [json.loads(line) for line in (run / role / "worker.jsonl").read_text().splitlines()]
            assert records[-1]["event"] == "complete", role
            assert (run / role / "process.jsonl").stat().st_size > 0, role
        assert (run / "stop.json").exists()
        assert not list(run.glob("*.failed.json"))
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
