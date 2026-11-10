# Local MoQT Testbed Implementation Plan

> Execution: continue the implementation requested by the user, using the existing project agents for independent client and ICE work. The submitted Progress Report 1 supplies the project design; this plan narrows its first experiment.

**Goal:** Collect reproducible preliminary measurements from the real draft-16 relay and provide a runnable PACE ICE procedure.

**Architecture:** An unchanged pinned relay forwards one paced synthetic track. A Rust client creates independent QUIC sessions and records JSONL observations. Python starts processes, samples the relay, summarizes measurements, and keeps the configuration with the raw data.

**Tech Stack:** Rust 1.90, Tokio, Quinn, Cloudflare moq-rs draft-16, Python 3 standard library, OpenSSL.

**Spec:** [Experiment design](../../experiment-design.md), based on the submitted Group 16 Progress Report 1.

## Global constraints

- Real protocol traffic; no simulated results presented as relay measurements.
- Stock relay revision `3b2b584b47e4a18f3a6bf48dc9a665c736743443`.
- Keep TLS private keys, build products, and exploratory runs out of Git.
- Preserve selected raw results with exact commands and revisions.
- Local findings are not PACE findings; no unimplemented scheduler claims.
- Frequent commits at independently useful milestones.

## Review focus

- Client application buffering can conceal transport backpressure: pause the media session and verify recovery/flow-control evidence.
- A successful process exit can still hide failed sessions: check all expected ready/completion records.
- No deliveries can make latency look good: include missing clients and delivered bytes.
- Old or incomplete run folders can contaminate output: create new folders and record failures.
- Distributed timestamps can mislead: label clock requirements and withhold cross-node latency claims until checked.

## Task 1: Pin the baseline

- [x] Commit the upstream submodule, toolchain, design, and README.
- [x] Build `cargo build --release --locked -p moq-relay-ietf --features metrics-prometheus` in `vendor/moq-rs`.
- [x] Check `vendor/moq-rs/target/release/moq-relay-ietf --help` against launcher flags.

## Task 2: Native workload client

Files: `Cargo.toml`, `Cargo.lock`, `src/`.

- [x] Add `moqt-load publish` and `moqt-load subscribe`, using the pinned transport library.
- [x] Common flags: `--relay`, `--tls-root`, `--namespace`, `--duration`.
- [x] Publisher flags: `--bitrate`, `--fps`, `--group-frames`.
- [x] Subscriber flags: `--clients`, `--client-offset`, `--stall-clients`, `--stall-after`, `--stall-for`.
- [x] JSONL object fields: `type`, `client`, `cohort`, `seq`, `bytes`, `sent_unix_us`, `received_unix_us`, `latency_ms`. Lifecycle records use `type` and `timestamp_unix_us`.
- [x] Test payload encoding/decoding and rejection of invalid inputs; run `cargo test`, `cargo fmt --check`, and `cargo clippy -- -D warnings` for this crate.
- [x] Commit the client after a real relay smoke test.

## Task 3: Local launcher and analysis

Files: `scripts/make_cert.py`, `scripts/run_local.py`, `scripts/analyze.py`, `tests/test_analysis.py`.

- [x] Generate a local TLS certificate with a matching host/IP SAN.
- [x] Launch relay, publisher, and subscriber generator; poll real readiness with a deadline and stop all children on failure.
- [x] Save `manifest.json`, publisher/subscriber JSONL, process samples, metrics snapshots, stderr, and exit statuses.
- [x] Test analysis with an explicit zero-delivery client, phase boundaries, and known percentile/fairness examples using `python3 -m unittest discover -s tests -v`.
- [x] Run a small successful smoke test, a deliberate bad-input test, then repeated healthy/stalled comparisons at several session counts.
- [x] Commit runner, tests, and analysis before saving selected results in a separate commit.

## Task 4: ICE procedure and report evidence

Files: `docs/pace-ice.md`, `scripts/ice.slurm`, `scripts/ice_worker.py`, `results/preliminary/`, `docs/progress-report-2.md`.

- [x] Provide a four-node allocation script with separate relay, publisher, and two load-generator roles, explicit timeouts, and shared result paths.
- [x] Link official ICE/Slurm documentation and label account-dependent values and untested cluster steps.
- [x] Syntax-check the launchers with `bash -n scripts/ice.slurm` and `python3 -m compileall -q scripts`.
- [x] Summarize actual local results with repetitions and limitations, retaining the six report sections and plain student-friendly wording.
- [x] Commit results and documentation; review repository status and transfer committed history back to the user's original local repo.

## Completion evidence

All twenty matrix runs completed; compressed raw observations and checksums are saved in `results/preliminary/2026-11-10/`. Rust release tests, strict Clippy, formatting, six analysis tests, Bash/Python syntax checks, and the four-worker local integration test passed. The report was checked against the measurements and its five-page PDF was rendered for visual review. ICE itself remains untested. The original local repo and GitHub branch receive each completed checkpoint.
