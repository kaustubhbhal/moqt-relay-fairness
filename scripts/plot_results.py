#!/usr/bin/env python3
"""Create report figures from per-run statistics (requires matplotlib)."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analyze import read_events


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("matrix", type=Path)
    p.add_argument("--summary", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    results = json.loads(args.summary.read_text())
    rows = [r for result in results for r in result["rows"] if r["phase"] == "stall" and r["cohort"] == "comparison_healthy"]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    colors = {False: "#2166ac", True: "#d6604d"}
    counts = sorted({r["total_clients"] for r in rows})
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), layout="constrained")
    for ax, field, title, ylabel in zip(axes,
            ("relay_rss_peak_mib", "latency_p99_ms"),
            ("Relay memory during the pause interval", "P99 delivery latency: healthy cohort"),
            ("Peak resident memory (MiB)", "Publisher-to-receiver time (ms)")):
        for i, count in enumerate(counts):
            for stalled in (False, True):
                values = [r[field] for r in rows if r["total_clients"] == count and bool(r["stall_clients"]) == stalled]
                center = i + (.16 if stalled else -.16)
                jitter = [(j - (len(values) - 1) / 2) * .025 for j in range(len(values))]
                ax.scatter([center + j for j in jitter], values, color=colors[stalled], s=30, alpha=.8,
                           label=("50% paused" if stalled else "No pauses") if i == 0 else None, zorder=3)
                ax.plot([center - .09, center + .09], [statistics.median(values)] * 2, color=colors[stalled], lw=2.5)
        ax.set_xticks(range(len(counts)), [str(n) for n in counts])
        ax.set_xlabel("Total subscribers")
        ax.set_ylabel(ylabel)
        ax.set_title(title, fontsize=11, pad=12)
        ax.grid(axis="y", alpha=.2)
        ax.set_ylim(bottom=0)
        ax.legend(frameon=False, fontsize=9)
    fig.suptitle("Unmodified draft-16 relay · loopback · 4 Mbit/s source", fontsize=13)
    fig.savefig(args.out / "baseline-comparison.png", dpi=200)
    fig.savefig(args.out / "baseline-comparison.pdf")
    plt.close(fig)

    # Show all repetitions; no cherry-picked representative trajectory.
    fig, axes = plt.subplots(1, len(counts), figsize=(9, 3.5), sharey=True, layout="constrained", squeeze=False)
    for ax, count in zip(axes[0], counts):
        labelled = set()
        for result in results:
            run = args.matrix / result["run"]
            manifest = json.loads((run / "manifest.json").read_text())
            if manifest["config"]["clients"] != count:
                continue
            paused = bool(manifest["config"]["stall_clients"])
            records = read_events(run / "subscribers.jsonl")
            ready = [e["timestamp_unix_us"] for e in records if e.get("type") == "ready"]
            anchor = statistics.median(ready)
            points = [s for s in read_events(run / "process.jsonl") if s["role"] == "relay"]
            ax.plot([(s["timestamp_unix_us"] - anchor) / 1e6 for s in points],
                    [s["rss_bytes"] / 1024 ** 2 for s in points], color=colors[paused], alpha=.55,
                    lw=1, label=("50% paused" if paused else "No pauses") if paused not in labelled else None)
            labelled.add(paused)
        ax.axvspan(5, 20, color="#888888", alpha=.10)
        ax.set_xlim(0, 30)
        ax.set_title(f"{count} subscribers", fontsize=11)
        ax.set_xlabel("Seconds since subscriber readiness")
        ax.grid(alpha=.15)
        ax.legend(frameon=False, fontsize=9, loc="upper left")
    axes[0][0].set_ylabel("Relay resident memory (MiB)")
    fig.suptitle("Relay memory over time · all five repetitions per condition", fontsize=13)
    fig.savefig(args.out / "memory-timeline.png", dpi=200)
    fig.savefig(args.out / "memory-timeline.pdf")
    plt.close(fig)

    # Machine-readable condition medians and observed ranges used by the report.
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["total_clients"], row["stall_clients"])].append(row)
    report = []
    for (clients, stalled), group in sorted(grouped.items()):
        entry = {"clients": clients, "stall_clients": stalled, "repetitions": len(group)}
        for field in ("relay_rss_peak_mib", "latency_p99_ms", "mean_client_goodput_mbps",
                      "mean_client_timely_goodput_mbps", "publisher_actual_objects_per_second",
                      "relay_cpu_percent_one_core", "subscribers_cpu_percent_one_core"):
            values = [r[field] for r in group]
            entry[field] = {"median": statistics.median(values), "min": min(values), "max": max(values)}
        report.append(entry)
    (args.out / "condition-summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
