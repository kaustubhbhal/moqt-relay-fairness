#!/usr/bin/env python3
"""Plot per-run policy comparisons; dots are runs and bars are medians, not CIs."""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def numeric(value, name, allow_none=False):
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: expected a number, got {value!r}")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name}: expected a finite, nonnegative number")
    return value


def one_row(result, cohort):
    matches = [row for row in result["rows"]
               if row["phase"] == "recovery" and row["cohort"] == cohort]
    if len(matches) != 1:
        raise ValueError(f"{result['run']}: expected one recovery row for {cohort}")
    return matches[0]


def load_conditions(path):
    results = json.loads(path.read_text())
    if not isinstance(results, list) or not results:
        raise ValueError("Expected a nonempty analyzer summary.json list")
    groups = defaultdict(list)
    clients, caps, deadlines, durations, timeouts, names = set(), set(), set(), set(), set(), set()
    for result in results:
        run = result["run"]
        if run in names:
            raise ValueError(f"Duplicate run name: {run}")
        names.add(run)
        healthy = one_row(result, "comparison_healthy")
        all_clients = one_row(result, "all")
        total = numeric(healthy["total_clients"], "total_clients")
        stalled = numeric(healthy["stall_clients"], "stall_clients")
        if total < 2 or int(total) != total or total % 2:
            raise ValueError("Expected an even total client count of at least two")
        if stalled not in (0, total // 2):
            raise ValueError("Expected no-stall and half-stalled comparison conditions")
        if healthy["clients"] != total // 2 or all_clients["clients"] != total:
            raise ValueError(f"{run}: unexpected healthy/all cohort size")
        timeout = healthy["max_subgroup_age_ms"]
        if timeout is not None:
            if numeric(timeout, "max_subgroup_age_ms") <= 0:
                raise ValueError("Enabled timeout must be positive")
            timeouts.add(timeout)
        cap = numeric(healthy["egress_limit_mbps"], "egress_limit_mbps")
        if cap <= 0:
            raise ValueError("This figure requires a positive shared UDP cap")
        clients.add(int(total))
        caps.add(cap)
        deadlines.add(numeric(healthy["deadline_ms"], "deadline_ms"))
        durations.add(numeric(healthy["phase_seconds"], "phase_seconds"))
        terminated = numeric(all_clients["terminated_clients_total"], "terminated_clients_total")
        if terminated > total or int(terminated) != terminated:
            raise ValueError(f"{run}: invalid termination count")
        record = {"run": run, "termination_percent": 100 * terminated / total}
        for field in ("latency_p99_ms", "mean_client_timely_goodput_mbps", "relay_rss_peak_mib"):
            record[field] = numeric(healthy[field], field, allow_none=True)
        groups[(int(stalled), timeout)].append(record)
    if any(len(values) != 1 for values in (clients, caps, deadlines, durations, timeouts)):
        raise ValueError("Use one client count, cap, deadline, recovery duration, and enabled timeout")
    total = clients.pop()
    timeout = timeouts.pop()
    order = [(0, None), (0, timeout), (total // 2, None), (total // 2, timeout)]
    if set(groups) != set(order):
        raise ValueError("All four no/half-stall × timeout-off/on groups are required")
    for records in groups.values():
        records.sort(key=lambda record: record["run"])
    return groups, order, total, caps.pop(), deadlines.pop(), durations.pop(), timeout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path, help="analyzer summary.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preview", action="store_true",
                        help="Watermark a rendering check as unsuitable for reporting results")
    args = parser.parse_args()
    try:
        groups, order, total, cap, deadline, recovery_seconds, timeout = load_conditions(args.summary)
    except (KeyError, ValueError, TypeError) as error:
        parser.error(str(error))

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42})
    fig, axes = plt.subplots(2, 2, figsize=(10.6, 7.6))
    fig.subplots_adjust(left=.09, right=.98, bottom=.18, top=.82, hspace=.70, wspace=.29)
    labels = [f"{stalled} stalled\nTimeout {'off' if age is None else f'{age / 1000:g} s'}\nn = {len(groups[(stalled, age)])}"
              for stalled, age in order]
    panels = [
        ("latency_p99_ms", "A  Healthy-client recovery P99", "Delivery latency (ms)"),
        ("mean_client_timely_goodput_mbps", "B  Healthy-client timely goodput", "Mean per-client goodput (Mbit/s)"),
        ("relay_rss_peak_mib", "C  Relay peak RSS during recovery", "Sampled resident memory (MiB)"),
        ("termination_percent", "D  Subscriptions terminated: whole run", "All intended clients terminated (%)"),
    ]
    missing_notes = []
    for axis, (field, title, ylabel) in zip(axes.flat, panels):
        for index, key in enumerate(order):
            records = groups[key]
            values = [record[field] for record in records if record[field] is not None]
            color = "#2166ac" if key[1] is None else "#b35806"
            if values:
                offsets = ([0] if len(values) == 1 else
                           [-.11 + .22 * position / (len(values) - 1)
                            for position in range(len(values))])
                axis.scatter([index + offset for offset in offsets], values,
                             s=35, color=color, alpha=.8, zorder=3)
                median = statistics.median(values)
                axis.plot([index - .18, index + .18], [median, median],
                          color="#202020", linewidth=2.4, zorder=4)
            missing = len(records) - len(values)
            if missing:
                axis.text(index, .94, f"N/A: {missing}", ha="center", va="top",
                          fontsize=8, color="#555555", transform=axis.get_xaxis_transform())
                missing_notes.append(f"{field}, {key[0]} stalled / timeout {key[1]}: {missing} unavailable")
        axis.set_xlim(-.5, 3.5)
        axis.set_xticks(range(4), labels, fontsize=8)
        axis.set_title(title, fontsize=11, loc="left", pad=10)
        axis.set_ylabel(ylabel)
        axis.grid(axis="y", color="#dddddd", linewidth=.6, zorder=0)
        axis.set_ylim(bottom=0)
        if field == "mean_client_timely_goodput_mbps":
            axis.set_ylim(bottom=-.03 * max(1, axis.get_ylim()[1]))
        if field == "termination_percent":
            # Padding leaves dots at zero visible rather than clipping half.
            axis.set_ylim(-3, 103)
            axis.set_yticks([0, 25, 50, 75, 100])

    fig.suptitle(f"{cap:g} Mbit/s UDP egress cap · {total} subscribers", fontsize=15, y=.965)
    fig.text(.5, .918,
             f"Recovery interval: {recovery_seconds:g} s · timely delivery ≤ {deadline:g} ms · "
             f"fixed timeout {timeout / 1000:g} s", ha="center", fontsize=10)
    fig.text(.5, .035,
             "Each dot is one run; black bars are medians. No confidence intervals are shown.\n"
             "Healthy clients retain fixed time/client denominators; terminations include every intended client.",
             ha="center", va="bottom", fontsize=9)
    if args.preview:
        fig.text(.5, .875, "RENDER CHECK ONLY — NOT EXPERIMENTAL EVIDENCE",
                 ha="center", color="#a52828", fontsize=11, weight="bold")

    args.out.mkdir(parents=True, exist_ok=True)
    stem = "policy-comparison-preview" if args.preview else "policy-comparison"
    fig.savefig(args.out / f"{stem}.png", dpi=220)
    fig.savefig(args.out / f"{stem}.pdf")
    plt.close(fig)
    counts = "; ".join(f"{stalled} stalled, timeout {'off' if age is None else f'{age:g} ms'}: "
                       f"{len(groups[(stalled, age)])} runs" for stalled, age in order)
    caption = (
        ("RENDER CHECK ONLY. These outputs must not be used as experimental evidence.\n\n" if args.preview else "") +
        f"Four-condition relay comparison at an aggregate {cap:g} Mbit/s outgoing UDP-payload cap "
        f"with {total} subscribers. Panels A–C show the {recovery_seconds:g}-second recovery phase: "
        "P99 among received Objects for the fixed healthy comparison cohort, mean timely goodput "
        f"per intended healthy client (deadline {deadline:g} ms), and sampled peak relay RSS. "
        "Panel D shows observed subscription terminations over the whole run divided by all "
        "intended clients; it is not a fraction of the stalled clients or a recovery-only count. "
        "Each dot represents one run and each black bar its condition's median; no confidence "
        "interval is implied. Zero-delivery clients remain in throughput denominators. "
        "Unavailable latency or memory observations are marked N/A and omitted from that median, "
        "never replaced with zero. Lower delivered-object P99 alone does not establish better "
        "service after subscriptions are terminated. Peak RSS is sampled process memory, not "
        "an Object-cache measurement.\n\n" + counts + "\n" +
        ("Unavailable observations: " + "; ".join(missing_notes) + "\n" if missing_notes else "") +
        f"Source: {args.summary.resolve()}\n" +
        f"Source SHA-256: {hashlib.sha256(args.summary.read_bytes()).hexdigest()}\n"
    )
    (args.out / f"{stem}-caption.txt").write_text(caption)
    print(args.out / f"{stem}.png")


if __name__ == "__main__":
    main()
