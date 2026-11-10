#!/usr/bin/env python3
"""Run a fixed, randomized-order baseline matrix, stopping on any failed run."""
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
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("--clients", type=int, nargs="+", default=[16, 64])
    p.add_argument("--seed", type=int, default=4251)
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    if args.repeats < 1 or any(n < 2 or n % 2 for n in args.clients):
        p.error("positive repeats and even client counts >= 2 required")
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = (args.out or ROOT / "results" / f"local-matrix-{tag}").resolve()
    out.mkdir(parents=True, exist_ok=False)
    rng = random.Random(args.seed)
    schedule = []
    for repeat in range(1, args.repeats + 1):
        conditions = [(n, s) for n in args.clients for s in (0, n // 2)]
        rng.shuffle(conditions)
        schedule.extend({"repeat": repeat, "clients": n, "stall_clients": s,
                         "directory": f"n{n}-s{s}-r{repeat}"} for n, s in conditions)
    (out / "schedule.json").write_text(json.dumps({"seed": args.seed, "runs": schedule}, indent=2) + "\n")
    for number, run in enumerate(schedule, 1):
        print(f"[{number}/{len(schedule)}] {run['directory']}", flush=True)
        subprocess.run([sys.executable, str(ROOT / "scripts/run_local.py"),
                        "--clients", str(run["clients"]), "--stall-clients", str(run["stall_clients"]),
                        "--duration", "30", "--stall-after", "5", "--stall-for", "15",
                        "--max-uni-streams", "1", "--label", run["directory"],
                        "--out", str(out / run["directory"])], check=True, cwd=ROOT)
    subprocess.run([sys.executable, str(ROOT / "scripts/analyze.py"),
                    *[str(out / run["directory"]) for run in schedule],
                    "--out", str(out / "analysis")], check=True, cwd=ROOT)
    print(out, flush=True)


if __name__ == "__main__":
    main()
