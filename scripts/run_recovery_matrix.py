#!/usr/bin/env python3
"""Compare baseline, termination, and same-subscription recovery after short pauses."""
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
    p.add_argument("--pauses", type=float, nargs="+", default=[0.25, 1, 2, 4])
    p.add_argument("--clients", type=int, default=16)
    p.add_argument("--egress-mbps", type=float, default=80)
    p.add_argument("--timeout-ms", type=int, default=3000)
    p.add_argument("--seed", type=int, default=4253)
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    if args.repeats < 1 or args.clients < 2 or args.clients % 2 or args.timeout_ms <= 0:
        p.error("require positive repeats/timeout and even client count >= 2")
    if any(not 0 < pause <= 60 for pause in args.pauses) or len(set(args.pauses)) != len(args.pauses):
        p.error("pause values must be unique, positive, finite and <=60 seconds")
    build_path = args.build_manifest.resolve()
    build = json.loads(build_path.read_text())
    if "client_binary" not in build:
        p.error("build the patched client with build_variant.py --build-client")
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = (args.out or ROOT / "results" / f"local-recovery-{tag}").resolve()
    out.mkdir(parents=True, exist_ok=False)
    rng = random.Random(args.seed)
    schedule = []
    for repeat in range(1, args.repeats + 1):
        conditions = [(args.clients // 2, pause, policy) for pause in args.pauses
                      for policy in ("baseline", "terminate", "skip")]
        conditions += [(0, max(args.pauses), policy) for policy in ("baseline", "terminate", "skip")]
        rng.shuffle(conditions)
        for stalled, pause, policy in conditions:
            schedule.append({"repeat": repeat, "clients": args.clients, "stall_clients": stalled,
                             "stall_for": pause, "policy": policy,
                             "directory": f"n{args.clients}-s{stalled}-p{pause:g}-{policy}-r{repeat}"})
    (out / "schedule.json").write_text(json.dumps({"seed": args.seed, "runs": schedule}, indent=2) + "\n")
    for index, run in enumerate(schedule, 1):
        print(f"[{index}/{len(schedule)}] {run['directory']}", flush=True)
        command = [sys.executable, str(ROOT / "scripts/run_local.py"),
                   "--clients", str(args.clients), "--stall-clients", str(run["stall_clients"]),
                   "--duration", str(15 + run["stall_for"]), "--stall-after", "5",
                   "--stall-for", str(run["stall_for"]), "--egress-mbps", str(args.egress_mbps),
                   "--relay-binary", build["binary"], "--load-binary", build["client_binary"],
                   "--variant-build-manifest", str(build_path), "--allow-policy-termination",
                   "--allow-subgroup-reset", "--delivery-timeout-ms", str(args.timeout_ms),
                   "--label", run["directory"], "--out", str(out / run["directory"])]
        if run["policy"] != "baseline":
            command += ["--max-subgroup-age-ms", str(args.timeout_ms),
                        "--subgroup-timeout-action", run["policy"]]
        subprocess.run(command, cwd=ROOT, check=True)
    directories = [str(out / run["directory"]) for run in schedule]
    subprocess.run([sys.executable, str(ROOT / "scripts/analyze.py"), *directories,
                    "--out", str(out / "analysis")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/analyze_recovery.py"), *directories,
                    "--out", str(out / "recovery")], cwd=ROOT, check=True)
    print(out, flush=True)


if __name__ == "__main__":
    main()
