# MoQT relay fairness

CS 4251 Group 16's experiment setup for studying how stalled subscribers affect a Media over QUIC relay.

The first milestone measures the existing relay. It does not yet implement the cross-session scheduler proposed in Progress Report 1. We use actual QUIC connections and synthetic, paced media objects; these are transport experiments, not video playback tests.

Cloudflare's relay is pinned to draft-16 revision `3b2b584b47e4a18f3a6bf48dc9a665c736743443` under `vendor/moq-rs`. Keeping the version fixed makes repeated experiments comparable with our submitted report. Initialize it with `git submodule update --init --recursive` after cloning.

See [the experiment design](docs/experiment-design.md), [measurement notes](docs/measurement-notes.md), and [PACE ICE procedure](docs/pace-ice.md).

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

Direct `PUBLISH` tests downstream shared-track fan-out. It does not test upstream `SUBSCRIBE` deduplication. The relay has no added bandwidth cap or fairness policy in this milestone.

## Checks

```bash
cargo test --release --locked
cargo clippy --release --locked --all-targets -- -D warnings
cargo fmt --check
python3 -m unittest discover -s tests -v
bash -n scripts/ice.slurm
python3 -m compileall -q scripts
```

## Repository layout

- `src/main.rs`: native publisher, subscriber sessions, and measurement events.
- `scripts/run_local.py`, `scripts/run_matrix.py`: isolated local runs and the repeated experiment.
- `scripts/analyze.py`: cohort/phase statistics with zero-delivery clients retained.
- `scripts/ice.slurm`, `scripts/ice_worker.py`: prepared four-node cluster launchers.
- `vendor/moq-rs`: unchanged, pinned upstream source.
- `results/`: raw experiments and selected evidence; generated local/ICE runs are ignored by default.

The next implementation milestone is a controlled shared egress budget, followed by session scheduling and backlog limits. Neither DRR nor the adaptive policy is implemented here yet.
