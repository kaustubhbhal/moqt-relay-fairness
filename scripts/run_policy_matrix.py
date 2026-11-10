#!/usr/bin/env python3
"""Compare a shared egress cap with and without a fixed forwarding timeout."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build-manifest", type=Path, required=True)
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("--clients", type=int, default=16)
    p.add_argument("--egress-mbps", type=float, default=80)
    p.add_argument("--timeout-ms", type=int, default=3000)
    p.add_argument("--seed", type=int, default=4252)
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    if args.repeats < 1 or args.clients < 2 or args.clients % 2 or args.timeout_ms < 1:
        p.error("positive repeats/timeout and an even client count >= 2 required")
    build_path = args.build_manifest.resolve()
    build = json.loads(build_path.read_text())
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = (args.out or ROOT / "results" / f"local-policy-{tag}").resolve()
    out.mkdir(parents=True, exist_ok=False)
    rng = random.Random(args.seed)
    schedule = []
    for repeat in range(1, args.repeats + 1):
        conditions = [(s, t) for s in (0, args.clients // 2) for t in (None, args.timeout_ms)]
        rng.shuffle(conditions)
        for stalled, timeout in conditions:
            schedule.append({"repeat": repeat, "clients": args.clients, "stall_clients": stalled,
                             "timeout_ms": timeout, "egress_mbps": args.egress_mbps,
                             "directory": f"n{args.clients}-s{stalled}-t{timeout or 0}-r{repeat}"})
    (out / "schedule.json").write_text(json.dumps({"seed": args.seed, "runs": schedule}, indent=2) + "\n")
    for index, run in enumerate(schedule, 1):
        print(f"[{index}/{len(schedule)}] {run['directory']}", flush=True)
        command = [sys.executable, str(ROOT / "scripts/run_local.py"),
                   "--clients", str(args.clients), "--stall-clients", str(run["stall_clients"]),
                   "--duration", "30", "--stall-after", "5", "--stall-for", "15",
                   "--egress-mbps", str(args.egress_mbps), "--relay-binary", build["binary"],
                   "--variant-build-manifest", str(build_path), "--allow-policy-termination",
                   "--label", run["directory"], "--out", str(out / run["directory"])]
        if run["timeout_ms"] is not None:
            command += ["--max-subgroup-age-ms", str(run["timeout_ms"])]
        subprocess.run(command, cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/analyze.py"),
                    *[str(out / run["directory"]) for run in schedule],
                    "--out", str(out / "analysis")], cwd=ROOT, check=True)
    print(out, flush=True)


if __name__ == "__main__":
    main()
