# MoQT relay fairness

The current implementation adds **per-session DRR and fixed retained-payload budgets**. Start with [session isolation](docs/session-isolation.md) for the code scope, controlled comparisons, and reproduction commands. Earlier timeout/recovery results below remain historical supporting experiments.

CS 4251 Group 16's experiment setup for studying how stalled subscribers affect a Media over QUIC relay.

The first milestone measures the existing relay. The second adds a shared UDP egress cap and an optional fixed subscription timeout. The third skips expired media streams so stalled clients can return to live on the same subscription. The fourth milestone implements per-session DRR and fixed payload reservation budgets; adaptive budgets remain future work. We use actual QUIC connections and synthetic, paced media objects; these are transport experiments, not video playback tests.

Cloudflare's relay is pinned to draft-16 revision `3b2b584b47e4a18f3a6bf48dc9a665c736743443` under `vendor/moq-rs`. Keeping the version fixed makes repeated experiments comparable with our submitted report. Initialize it with `git submodule update --init --recursive` after cloning.

See [the experiment design](docs/experiment-design.md), [measurement notes](docs/measurement-notes.md), and [PACE ICE procedure](docs/pace-ice.md).

For the patched relay, see [the capped-relay comparison](docs/capped-relay-experiments.md). It includes a separate reproducible build, identical-cap comparisons, and termination accounting that retains disconnected clients in throughput denominators.

**Completed:** 20 baseline runs, 20 capped-policy runs, and [75 short-pause recovery runs](results/recovery/2026-11-10/README.md). With four-second pauses and an 80 Mbit/s cap, skip recovered all 40 paused clients without disconnecting them and reduced median healthy-client P99 from 174 to 48 ms. Recovery varied: skip's run medians ranged from 5 ms to 2.104 seconds. Shorter pauses did not activate the three-second policy. See the [implementation guide](docs/live-recovery-experiments.md), [Progress Report 2 draft](docs/progress-report-2.md), or [formatted PDF](output/pdf/progress-report-2-group-16.pdf).

## Build

Install Rust through rustup, Python 3, and OpenSSL. The Python runner uses only the standard library. On Linux, use a normal compiler toolchain as well. Run from the repository root:

```bash
git submodule update --init --recursive
cargo build --manifest-path vendor/moq-rs/Cargo.toml --release --locked \
  -p moq-relay-ietf --features metrics-prometheus
cargo build --release --locked
```

The checked-in `rust-toolchain.toml` selects Rust 1.90.0. Keep Cargo's default target directories for these commands. The first build downloads public dependencies. Avoid a cloud-synced folder for build products and experiment logs if it causes filesystem delays.

## Local smoke test

```bash
python3 scripts/run_local.py --clients 4 --stall-clients 2 \
  --duration 8 --stall-after 2 --stall-for 3 --label smoke
```

The script starts and stops its own relay and clients, chooses free loopback ports, and creates a short-lived trusted certificate. Keys stay in ignored `.local/certs/`. It prints the run directory. A failed process, missing subscriber, or protocol error makes the run fail; inspect the saved diagnostics before drawing conclusions.

## Repeated baseline experiment

```bash
python3 scripts/run_matrix.py --repeats 5 --clients 16 64 --seed 4251
```

This takes roughly eleven minutes. Each run lasts 30 seconds per accepted subscriber: five seconds before the pause, fifteen seconds paused, and ten seconds after resuming. The no-stall controls use the same analysis intervals. Each repetition tests all four conditions in a seeded shuffled order. The script stops if any run fails and retains its logs.

Analyze selected runs separately with:

```bash
python3 scripts/analyze.py results/local-RUN-DIRECTORY --out results/analysis
```

Replace `local-RUN-DIRECTORY` with the directory printed by the runner. Multiple directories are accepted. `summary.csv` includes per-run, per-phase results; `summary.json` also includes transport evidence from the paused clients. The analysis accepts either plain or gzip-compressed JSONL files.

## What the workload does

`moqt-load publish` sends one shared track through the relay using direct `PUBLISH`. It generates 16,666-byte Objects at 30/s, or 3.99984 Mbit/s. A new subgroup starts every 30 Objects. There is no video encoder or player. The receiver verifies every Object's sequence/timestamp header and payload.

`moqt-load subscribe` creates independent QUIC sessions. Paused clients stop polling MoQT's session-processing future, while Quinn keeps handling transport packets and acknowledgements. Both cohorts advertise a 64 KiB connection receive window, 32 KiB stream receive window, and **one incoming unidirectional stream at a time**. That last setting avoids a receiver-cache recovery failure observed with overlapping incoming groups in the pinned library. It also constrains the workload; these results do not describe every possible client configuration.

Direct `PUBLISH` tests downstream shared-track fan-out. It does not test upstream `SUBSCRIBE` deduplication. The original baseline uses the unmodified relay. Capped experiments select the separate patched executable explicitly.

## Checks

```bash
cargo test --release --locked
cargo clippy --release --locked --all-targets -- -D warnings
cargo fmt --check
python3 -m unittest discover -s tests -v
bash -n scripts/ice.slurm
python3 -m compileall -q scripts
```

`python3 tests/ice_local_smoke.py` additionally checks the four worker roles using local processes and real QUIC. It does not run on ICE or invoke Slurm.

To regenerate the report PDF and figures, install the optional `requirements-report.txt` dependencies in a Python environment, then run `python3 scripts/build_report_pdf.py docs/progress-report-2.md --out output/pdf/progress-report-2-group-16.pdf`. Figure generation commands are included with the saved results.

## Repository layout

- `src/main.rs`: native publisher, subscriber sessions, and measurement events.
- `scripts/run_local.py`, `scripts/run_matrix.py`: isolated local runs and the repeated experiment.
- `scripts/analyze.py`: cohort/phase statistics with zero-delivery clients retained.
- `scripts/ice.slurm`, `scripts/ice_worker.py`: prepared four-node cluster launchers.
- `vendor/moq-rs`: unchanged, pinned upstream source.
- `results/`: raw experiments and selected evidence; generated local/ICE runs are ignored by default.

The shared egress cap, fixed forwarding timeout, and same-subscription recovery are implemented as isolated patches. The cumulative third patch adds session DRR and fixed retained-payload budgets. Adaptive limits remain a later step.
