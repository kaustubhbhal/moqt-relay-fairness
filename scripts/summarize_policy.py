#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 MoQT Relay Fairness project contributors
# SPDX-License-Identifier: MIT
"""Group analyze.py JSON results without pooling Objects or discarding missing latency."""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics


GROUP_FIELDS = (
    "total_clients", "stall_clients", "max_subgroup_age_ms", "egress_limit_mbps",
    "phase", "cohort", "phase_seconds", "deadline_ms", "clients", "subgroup_timeout_action", "stall_for",
)
METRICS = (
    "latency_median_ms", "latency_p99_ms", "mean_client_goodput_mbps",
    "mean_client_timely_goodput_mbps", "terminated_clients_total",
    "termination_fraction_total", "zero_delivery_clients", "objects",
    "jain_goodput", "late_object_fraction", "relay_rss_peak_mib",
    "relay_rss_median_mib", "relay_cpu_percent_one_core",
    "measured_udp_egress_mbps", "publisher_actual_objects_per_second",
    "publisher_actual_mbps", "publisher_cpu_percent_one_core",
    "subscribers_cpu_percent_one_core",
)
NOTES = (
    "Each statistic summarizes run-level measurements; Objects are not pooled across runs.",
    "Ranges are observed run minima and maxima, not confidence intervals.",
    "Undefined values remain null. Each metric reports its defined and undefined run counts.",
    "Goodput retains all expected clients for the full phase, including terminated clients.",
    "Latency and late-Object fraction describe received Objects only; absent delivery has no P99.",
    "Termination counts/fractions cover the entire run and are repeated across phase rows.",
    "Relay RSS, CPU, and UDP egress are shared relay measurements repeated across cohorts.",
    "UDP egress includes QUIC overhead and retransmissions; payload goodput does not.",
    "Grouping uses settings available in analyzer output; verify other workload, burst, binary, "
    "and patch settings match before interpreting comparisons.",
)


def aggregate(values):
    """Keep undefined runs visible instead of silently treating them as zero."""
    defined = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"expected a finite numeric measurement or null, got {value!r}")
        defined.append(value)
    return {
        "runs": len(values), "defined_runs": len(defined),
        "undefined_runs": len(values) - len(defined),
        "median": statistics.median(defined) if defined else None,
        "min": min(defined) if defined else None,
        "max": max(defined) if defined else None,
    }


def summarize(inputs):
    buckets = defaultdict(list)
    seen_runs = set()
    for source in inputs:
        runs = json.loads(Path(source).read_text())
        if not isinstance(runs, list) or not runs:
            raise ValueError(f"{source}: expected a nonempty analyzer run list")
        for run in runs:
            name = run["run"]
            if not isinstance(name, str) or not name:
                raise ValueError(f"{source}: invalid run name")
            if name in seen_runs:
                raise ValueError(f"duplicate run {name!r}; supply each run only once")
            seen_runs.add(name)
            if not run["rows"]:
                raise ValueError(f"{name}: run has no measurement rows")
            seen_rows = set()
            for row in run["rows"]:
                if row["run"] != name:
                    raise ValueError(f"{name}: row names a different run")
                identity = (row["phase"], row["cohort"])
                if identity in seen_rows:
                    raise ValueError(f"{name}: duplicate phase/cohort {identity}")
                seen_rows.add(identity)
                # Old baseline summaries have no policy configuration or termination
                # measurements. Missing measurements remain undefined, never zero.
                settings = {field: row.get(field) for field in GROUP_FIELDS}
                for field in GROUP_FIELDS:
                    if field not in ("max_subgroup_age_ms", "egress_limit_mbps", "subgroup_timeout_action", "stall_for") and settings[field] is None:
                        raise ValueError(f"{name}: missing grouping field {field}")
                for field, value in settings.items():
                    if field in ("phase", "cohort") or (field == "subgroup_timeout_action" and value is not None):
                        if not isinstance(value, str) or not value:
                            raise ValueError(f"{name}: invalid {field}")
                    elif value is not None:
                        aggregate([value])  # Reject NaN/Infinity before grouping.
                key = tuple(settings[field] for field in GROUP_FIELDS)
                buckets[key].append(row)
    groups = []
    for key, rows in buckets.items():
        groups.append({
            **dict(zip(GROUP_FIELDS, key)),
            "timeout_enabled": key[2] is not None,
            "runs": len(rows), "run_names": sorted(row["run"] for row in rows),
            "metrics": {metric: aggregate([row.get(metric) for row in rows]) for metric in METRICS},
        })
    groups.sort(key=lambda g: (
        g["total_clients"], -1 if g["egress_limit_mbps"] is None else g["egress_limit_mbps"],
        {"pre_stall": 0, "stall": 1, "recovery": 2}.get(g["phase"], 3), g["phase"],
        g["cohort"], g["phase_seconds"], g["deadline_ms"], g["clients"],
        g["stall_clients"], -1 if g["max_subgroup_age_ms"] is None else g["max_subgroup_age_ms"],
    ))
    return {"schema_version": 1, "inputs": [str(Path(p)) for p in inputs],
            "run_count": len(seen_runs), "notes": list(NOTES), "groups": groups}


def cell(stat, digits=2, scale=1):
    count = f"{stat['defined_runs']}/{stat['runs']}"
    if stat["median"] is None:
        return f"undefined ({count})"
    values = [f"{stat[k] * scale:.{digits}f}" for k in ("median", "min", "max")]
    result = f"{values[0]} [{values[1]}, {values[2]}]"
    if stat["undefined_runs"]:
        result += f" ({count} defined)"
    return result


def escape(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown(summary):
    lines = ["# Capped-relay policy comparison", "",
             f"{summary['run_count']} runs. Cells show **median [minimum, maximum]** across runs.", ""]
    lines.extend(f"- {note}" for note in summary["notes"])
    contexts = defaultdict(list)
    for group in summary["groups"]:
        key = tuple(group[field] for field in (
            "total_clients", "egress_limit_mbps", "phase", "cohort",
            "phase_seconds", "deadline_ms", "clients",
        ))
        contexts[key].append(group)
    for (total, cap, phase, cohort, seconds, deadline, clients), groups in contexts.items():
        cap_label = "off" if cap is None else f"{cap:g} Mbit/s"
        lines.extend(["", f"## {total} clients; cap {cap_label}; {escape(phase)}; {escape(cohort)}", "",
                      f"Cohort: {clients} clients. Phase: {seconds:g} s. Timely-delivery target: {deadline:g} ms.", "",
                      "| Paused | Timeout (ms) | Runs | P99 (ms) | Payload (Mbit/s/client) | Timely payload (Mbit/s/client) | Terminated, whole run (%) |",
                      "| --- | --- | --- | --- | --- | --- | --- |"])
        for group in groups:
            m = group["metrics"]
            timeout = "off" if group["max_subgroup_age_ms"] is None else f"{group['max_subgroup_age_ms']:g}"
            if group.get("subgroup_timeout_action") is not None:
                timeout += f" / {group['subgroup_timeout_action']} / pause {group['stall_for']:g}s"
            prefix = f"| {group['stall_clients']} | {timeout} | {group['runs']} |"
            lines.append(prefix + " " + " | ".join((
                cell(m["latency_p99_ms"]), cell(m["mean_client_goodput_mbps"], 3),
                cell(m["mean_client_timely_goodput_mbps"], 3),
                cell(m["termination_fraction_total"], 1, 100),
            )) + " |")
        lines.extend(["", "| Paused | Timeout (ms) | Runs | Peak relay RSS (MiB) | Relay CPU (% of one core) | UDP egress (Mbit/s) | Zero-delivery clients |",
                      "| --- | --- | --- | --- | --- | --- | --- |"])
        for group in groups:
            m = group["metrics"]
            timeout = "off" if group["max_subgroup_age_ms"] is None else f"{group['max_subgroup_age_ms']:g}"
            if group.get("subgroup_timeout_action") is not None:
                timeout += f" / {group['subgroup_timeout_action']} / pause {group['stall_for']:g}s"
            lines.append(f"| {group['stall_clients']} | {timeout} | {group['runs']} | " + " | ".join((
                cell(m["relay_rss_peak_mib"]), cell(m["relay_cpu_percent_one_core"], 1),
                cell(m["measured_udp_egress_mbps"], 3), cell(m["zero_delivery_clients"], 1),
            )) + " |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summaries", type=Path, nargs="+", help="summary.json files from analyze.py")
    parser.add_argument("--out", type=Path, required=True, help="directory for policy-summary.json and .md")
    args = parser.parse_args()
    try:
        result = summarize(args.summaries)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "policy-summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    (args.out / "policy-summary.md").write_text(markdown(result))
    print(f"Grouped {result['run_count']} runs into {len(result['groups'])} groups in {args.out}")


if __name__ == "__main__":
    main()
