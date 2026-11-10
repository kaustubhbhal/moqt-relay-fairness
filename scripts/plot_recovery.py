#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 MoQT Relay Fairness project contributors
# SPDX-License-Identifier: MIT
"""Plot recovery.json as a four-panel figure, retaining censoring and run variation.

Example: MPLCONFIGDIR=/private/tmp/moqt-mpl python scripts/plot_recovery.py \
    analysis/recovery.json --out figures [--summary analysis/summary.json]
Use --preview for synthetic inputs; this visibly labels both output formats.
"""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics
import textwrap


def median(values):
    defined = [v for v in values if v is not None]
    return statistics.median(defined) if defined else None


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def prepare(data, external=None, censor_at=10):
    """Produce one observation per run; never pool client recovery times across runs."""
    if data.get("schema_version") != 1 or not data.get("runs"):
        raise ValueError("expected nonempty recovery.json schema_version 1")
    external_by_run = {}
    for item in external or []:
        if item["run"] in external_by_run:
            raise ValueError("duplicate run in optional analyzer summary")
        external_by_run[item["run"]] = item["rows"]
    seen, signatures, stalled_counts = set(), set(), set()
    mixed, controls = [], []
    variable = {"stall_for", "stall_clients", "duration", "subgroup_timeout_action", "max_subgroup_age_ms"}
    for run in data["runs"]:
        name, settings = run["run"], run["settings"]
        if name in seen:
            raise ValueError(f"duplicate run {name}")
        seen.add(name)
        signatures.add(json.dumps({k: v for k, v in settings.items() if k not in variable}, sort_keys=True))
        action = settings["subgroup_timeout_action"]
        action = "baseline" if action in ("off", "baseline") else action
        if action not in ("baseline", "terminate", "skip"):
            raise ValueError(f"unsupported action {action!r}")
        timeout = settings.get("max_subgroup_age_ms")
        condition = (action, timeout)
        embedded = run.get("healthy_phase_rows", [])
        rows = external_by_run.get(name, embedded)
        healthy_rows = [r for r in rows if r["cohort"] == "comparison_healthy" and r["phase"] == "recovery"]
        if len(healthy_rows) != 1:
            raise ValueError(f"{name}: expected one healthy recovery phase row")
        healthy_p99 = healthy_rows[0]["latency_p99_ms"]
        if healthy_p99 is not None:
            number(healthy_p99, "healthy P99")
        if name in external_by_run and embedded:
            original = [r for r in embedded if r["phase"] == "recovery"]
            if len(original) != 1 or original[0]["latency_p99_ms"] != healthy_p99:
                raise ValueError(f"{name}: embedded and external healthy P99 differ")
        row = {"run": name, "condition": condition, "pause": number(settings["stall_for"], "pause"),
               "healthy_p99": healthy_p99}
        if not settings["stall_clients"]:
            row["terminated"] = sum(c["terminated"] for c in run["clients"])
            row["eligible"] = len(run["clients"])
            controls.append(row)
            continue
        stalled_counts.add(settings["stall_clients"])
        clients = [c for c in run["clients"] if c["cohort"] == "stalled"]
        if len(clients) != settings["stall_clients"]:
            raise ValueError(f"{name}: paused cohort does not match stall_clients")
        planned_post = settings["duration"] - settings["stall_after"] - settings["stall_for"]
        if abs(planned_post - censor_at) > 0.5:
            raise ValueError(f"{name}: nominal post-pause duration differs from --censor-at")
        for client in clients:
            observed = number(client["post_reference_observation_seconds"], "observed seconds")
            if abs(observed - censor_at) > 0.5:
                raise ValueError(f"{name}: actual observation differs substantially from censor marker")
            delay = client["sustained_timely_seconds"]
            if delay is not None and (number(delay, "recovery delay") < 0 or delay + 1 > observed + 1e-6):
                raise ValueError(f"{name}: recovery window outside observation")
            if client["terminated"] and delay is not None:
                raise ValueError(f"{name}: terminated client marked recovered")
            if number(client["first5_timely_mbps"], "timely goodput") < 0:
                raise ValueError(f"{name}: negative goodput")
        row.update(eligible=len(clients), recovered=sum(c["sustained_timely_seconds"] is not None for c in clients),
                   terminated=sum(c["terminated"] for c in clients),
                   censored=sum(not c["terminated"] and c["sustained_timely_seconds"] is None for c in clients),
                   recovery=median([c["sustained_timely_seconds"] for c in clients]),
                   timely=statistics.mean(c["first5_timely_mbps"] for c in clients))
        row["terminated_fraction"] = row["terminated"] / row["eligible"]
        mixed.append(row)
    if not mixed:
        raise ValueError("no runs with paused clients")
    if len(signatures) != 1 or len(stalled_counts) != 1:
        raise ValueError("inputs mix non-comparable hardware/build/workload settings; plot each experiment separately")
    return mixed, controls


def condition_label(condition):
    action, timeout = condition
    title = {"baseline": "Baseline", "terminate": "Terminate", "skip": "Skip subgroup"}[action]
    return title if timeout is None else f"{title} ({timeout / 1000:g} s)"


def plot(mixed, controls, out, censor_at=10, preview=False, deadline_ms=150):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42, "ps.fonttype": 42})
    order = {"baseline": 0, "terminate": 1, "skip": 2}
    conditions = sorted({r["condition"] for r in mixed}, key=lambda c: (order[c[0]], c[1] or 0))
    if len(conditions) > 3:
        raise ValueError("at most three policy/timeout combinations fit this figure; split the inputs")
    colors = {c: {"baseline": "#3366a1", "terminate": "#c45d21", "skip": "#168570"}[c[0]] for c in conditions}
    durations = sorted({r["pause"] for r in mixed})
    buckets = defaultdict(list)
    for row in mixed:
        buckets[(row["condition"], row["pause"])].append(row)
    if any(not buckets[(c, d)] for c in conditions for d in durations):
        raise ValueError("incomplete policy × pause matrix; missing conditions must not look like zero results")
    fig, axes = plt.subplots(2, 2, figsize=(12.4, 9.1))
    panels = [(axes[0, 0], "healthy_p99", "Healthy clients: recovery-phase P99", "Latency (ms)"),
              (axes[0, 1], "recovery", "Paused clients: sustained timely recovery", "Seconds after actual resume"),
              (axes[1, 0], "timely", "Paused clients: first 5 s timely goodput", "Mean goodput per client (Mbps)"),
              (axes[1, 1], "terminated_fraction", "Paused clients: terminated subscriptions", "Fraction of paused clients")]
    count_labels = []
    for ci, condition in enumerate(conditions):
        offset = (ci - (len(conditions) - 1) / 2) * 0.19
        color = colors[condition]
        for ax, field, _, _ in panels:
            centers, medians = [], []
            for di, duration in enumerate(durations):
                rows = sorted(buckets[(condition, duration)], key=lambda r: r["run"])
                x = di + offset
                values = [r[field] for r in rows]
                med = median(values)
                centers.append(x)
                medians.append(float("nan") if med is None else med)
                for ri, row in enumerate(rows):
                    jitter = 0 if len(rows) == 1 else (ri / (len(rows) - 1) - 0.5) * 0.11
                    if row[field] is not None:
                        ax.scatter(x + jitter, row[field], s=23, color=color, alpha=0.62, edgecolors="white", linewidths=0.35, zorder=3)
                    if field == "recovery":
                        if row["censored"]:
                            ax.scatter(x + jitter, censor_at, marker="x", s=32, color=color, linewidths=1.2, zorder=4)
                        if row["terminated"]:
                            ax.scatter(x + jitter, censor_at, marker="v", s=30, facecolors="none", edgecolors=color, linewidths=1.1, zorder=4)
                if med is not None:
                    ax.plot([x - .065, x + .065], [med, med], color=color, linewidth=2.6, zorder=5)
                if field == "recovery":
                    recovered = sum(r["recovered"] for r in rows)
                    eligible = sum(r["eligible"] for r in rows)
                    text = f"{recovered}/{eligible} (n={len(rows)})"
                    count_labels.append((di, ci, text, color))
            ax.plot(centers, medians, color=color, linewidth=0.9, alpha=0.7)
    for ax, field, title, ylabel in panels:
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold", pad=10)
        ax.set_ylabel(ylabel)
        ax.set_xlabel("Pause duration (s; categorical spacing)")
        ax.set_xticks(range(len(durations)), [f"{d:g}" for d in durations])
        ax.set_xlim(-.55, len(durations) - .45)
        ax.grid(axis="y", color="#d9d9d9", linewidth=.5, zorder=0)
        ax.set_ylim(bottom=0)
        if field == "terminated_fraction":
            ax.set_ylim(-.035, 1.065)
            ax.set_yticks([0, .25, .5, .75, 1])
    recovery_ax = axes[0, 1]
    recovery_ax.axhline(censor_at, color="#777777", linewidth=.7, linestyle="--")
    recovery_ax.set_ylim(-.3, censor_at + 3.6)
    recovery_ax.set_yticks([0, 2, 4, 6, 8, censor_at])
    recovery_ax.text(.02, .995, "Recovered / eligible clients (n = runs)", transform=recovery_ax.transAxes, fontsize=8.2, va="top")
    for di, ci, text, color in count_labels:
        recovery_ax.text(di, censor_at + 2.1 - .55 * ci, text, color=color, ha="center", fontsize=8.2)
    handles = [Line2D([0], [0], color=colors[c], marker="o", linewidth=1.3, label=condition_label(c)) for c in conditions]
    handles.extend([Line2D([0], [0], linestyle="none", marker="x", color="#444444", label="Run includes censored client(s)"),
                    Line2D([0], [0], linestyle="none", marker="v", markerfacecolor="none", color="#444444", label="Run includes terminated client(s)")])
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, .953), ncol=3, frameon=False, fontsize=9)
    title = "SYNTHETIC PREVIEW — NOT EXPERIMENTAL RESULTS" if preview else "MoQT subscriber recovery across pause durations"
    fig.suptitle(title, y=.99, fontsize=14, fontweight="bold")
    footer = [f"Timely: latency ≤{deadline_ms:g} ms. Sustained recovery starts a fully observed 1 s window with ≥80% expected Objects, all timely, and no gap >3/fps.",
              "Dots: one run; bars/lines: median across runs. Goodput dots are client means, including zeros; P99 dots use the healthy cohort.",
              "Recovery dots: median among recovered clients in each run; only defined run medians contribute to bars. Counts retain every eligible client.",
              f"× and ▽ at {censor_at:g} s mark runs with censored or terminated clients, respectively; these are status markers, not recovery times."]
    if controls:
        summaries = []
        for condition in conditions:
            rows = [r for r in controls if r["condition"] == condition]
            if rows:
                p99 = median([r["healthy_p99"] for r in rows])
                latency = "undefined" if p99 is None else f"{p99:.2f} ms"
                summaries.append(f"{condition_label(condition)}: n={len(rows)}, P99 {latency}, terminated {sum(r['terminated'] for r in rows)}/{sum(r['eligible'] for r in rows)}")
        footer.append("No-pause controls (separate nominal window; median run P99): " + "; ".join(summaries))
    else:
        footer.append("No no-pause control runs supplied.")
    missing_p99 = sum(r["healthy_p99"] is None for r in mixed)
    if missing_p99:
        footer.append(f"Healthy P99 is undefined in {missing_p99}/{len(mixed)} paused runs; undefined values are omitted from P99 medians.")
    fig.text(.065, .018, "\n".join(textwrap.fill(line, width=170) for line in footer), fontsize=8, linespacing=1.5, va="bottom")
    fig.subplots_adjust(left=.075, right=.975, top=.845, bottom=.19, hspace=.43, wspace=.27)
    out.mkdir(parents=True, exist_ok=True)
    stem = "recovery-preview" if preview else "recovery"
    for suffix in ("png", "pdf"):
        fig.savefig(out / f"{stem}.{suffix}", dpi=220, facecolor="white")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recovery", type=Path)
    parser.add_argument("--summary", type=Path, help="Optional analyze.py summary.json; cross-checks embedded healthy P99")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--censor-at", type=float, default=10, help="Nominal post-resume observation in seconds (status-marker height)")
    parser.add_argument("--preview", action="store_true", help="Prominently label synthetic render; use preview filenames")
    args = parser.parse_args()
    try:
        if number(args.censor_at, "censor-at") <= 0:
            raise ValueError("--censor-at must be positive")
        data = json.loads(args.recovery.read_text())
        external = json.loads(args.summary.read_text()) if args.summary else None
        mixed, controls = prepare(data, external, args.censor_at)
        plot(mixed, controls, args.out, args.censor_at, args.preview,
             number(data["runs"][0]["settings"]["deadline_ms"], "deadline_ms"))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    print(f"Plotted {len(mixed)} paused runs and {len(controls)} controls in {args.out}")


if __name__ == "__main__":
    main()
