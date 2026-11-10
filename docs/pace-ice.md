# Running the testbed on PACE ICE

These instructions prepare a four-node experiment on Georgia Tech's ICE cluster. **No ICE run has been completed or claimed by this repository's setup work.** The launcher has been checked locally for syntax; cluster access, installed software, allocation limits, and communication between nodes still need to be checked on ICE. Local results are separate from cluster results.

## What a batch job means

You submit a small script to Slurm, the cluster's scheduler. Slurm waits until the requested computers are available, reserves them, and runs the script. `sbatch` returning a job number means the request was accepted; it does not mean the experiment finished or succeeded. Use `squeue` to see whether it is waiting or running, and inspect its logs and `sacct` status after it finishes.

The script requests four nodes, one process per node, eight allocated CPUs per process, 32 GiB of memory per node, and 30 minutes. The processes start native QUIC applications; there is no Docker or privileged network configuration.

| Slurm rank | Role | Work |
| --- | --- | --- |
| 0 | Relay | Stock pinned Cloudflare relay, TLS, and metrics snapshots |
| 1 | Publisher | One synthetic 4 Mb/s, 30 frame/s source |
| 2 | Client generator | First half of the independent subscriber connections |
| 3 | Client generator | Remaining subscriber connections |

An allocated CPU is a scheduler resource; eight requested CPUs do not establish the server's complete physical CPU model. The worker records `lscpu`, memory, kernel, interfaces, routes, and Slurm settings on each node. Check these records before describing the hardware in the report. The allocation does not request GPUs or guarantee exclusive access to entire physical nodes.

## 1. Get onto ICE and choose a working directory

Use the ICE access method provided by your course. The usual SSH endpoint is:

```bash
ssh YOUR_GT_USERNAME@login-ice.pace.gatech.edu
```

Follow the current GT VPN and sign-in instructions if required. An interactive web terminal is also available through [ICE Open OnDemand](https://ondemand-ice.pace.gatech.edu/). Do not put passwords or private SSH keys in this repository.

Use a shared directory that all allocated nodes can read. If your account provides the usual `~/scratch` directory, it is a convenient place for this checkout and generated outputs:

```bash
pace-quota
test -d "$HOME/scratch"
cd "$HOME/scratch"
```

If that directory is absent, use your course's assigned project/scratch location. Do not assume that `scratch` has a particular quota, backup policy, or lifetime. Check [ICE storage guidance, KB0042094](https://gatech.service-now.com/home?id=kb_article_view&sysparm_article=KB0042094) and preserve important results outside temporary storage. Transfer or clone this repository into the chosen directory, including its pinned submodule:

```bash
cd moqt-relay-fairness
git submodule update --init --recursive
mkdir -p logs results
```

The scripts must be submitted from the repository root. Slurm does not copy the checkout to the compute nodes automatically.

## 2. Build Linux binaries

The macOS binaries used for a laptop experiment will not run on ICE. Build the native Linux programs on ICE. First inspect available software and request a short compute allocation:

```bash
module avail
salloc --nodes=1 --ntasks=1 --cpus-per-task=8 --mem=32G --time=00:30:00
srun --pty bash
```

Inside that allocated shell, load the Rust/Python/compiler modules available to your account if needed. Exact module names are installation-specific; do not copy an unverified module name from another cluster. `salloc` behavior can differ between sites; `srun --pty bash` explicitly starts the shell within the allocation. Then run:

```bash
cd /YOUR/SHARED/PATH/moqt-relay-fairness
python3 --version
cargo --version
openssl version
cargo build --manifest-path vendor/moq-rs/Cargo.toml --release --locked \
  -p moq-relay-ietf --features metrics-prometheus
cargo build --release --locked
vendor/moq-rs/target/release/moq-relay-ietf --help
target/release/moqt-load --help
exit
```

End the allocation shell too if it remains open. The certificate helper uses Python's standard library and the `openssl` command, with no extra Python package required. Package downloads for the Rust build may require network access; if compute-node downloads are unavailable, fetch dependencies in a permitted environment before building. Do not run the load test on a login node.

The relay's `metrics-prometheus` build feature is required: supplying `--metrics-addr` without that feature only emits a warning and does not start the endpoint. The worker uses that endpoint for readiness and logging. Keep Cargo's default target directories for these commands; if you normally set `CARGO_TARGET_DIR`, unset it for this build or adjust the launcher paths explicitly.

## 3. Submit a short four-node check

First use the repository's local smoke-test procedure in a compute allocation. Once that works, submit a short distributed run:

```bash
mkdir -p logs results
MOQT_CLIENTS=16 MOQT_DURATION=20 MOQT_STALL_CLIENTS=0 \
  sbatch scripts/ice.slurm
squeue -u "$USER"
```

Keep the job ID printed by `sbatch`. The script intentionally does not hardcode a partition, QOS, account, or CPU feature. Check [ICE job submission, KB0042096](https://gatech.service-now.com/home?id=kb_article_view&sysparm_article=KB0042096) and your course's account settings if submission is rejected. Do not add a Phoenix `gts-...` account or `inferno`/`embers` QOS to an ICE job without verifying that it applies to your account.

After the smoke run passes, a longer example is:

```bash
MOQT_CLIENTS=128 MOQT_DURATION=180 MOQT_STALL_CLIENTS=32 \
MOQT_STALL_AFTER=60 MOQT_STALL_FOR=30 \
  sbatch scripts/ice.slurm
```

`MOQT_CLIENTS` and `MOQT_STALL_CLIENTS` are totals across both client machines, not per-machine values. Clients have unique IDs starting at zero; the first configured number of IDs stall. Consequently the stalled clients may all be on the first generator. The configuration records that placement. `MOQT_DURATION` is limited to 1,200 seconds by the worker so setup and cleanup fit within the default allocation. All time values must be finite; when any client stalls, its positive stall interval must finish before the run ends. Native processes default to `TOKIO_WORKER_THREADS=4`, which is recorded in their metadata and can be overridden in the submission environment.

For a trustworthy comparison, repeat each condition with the same client placement and parameters. Compare runs without stalls against runs with stalls. Check generator CPU headroom before concluding that a throughput limit belongs to the relay. Separate nodes avoid a shared laptop event loop, but do not by themselves establish that generators are fast enough.

## 4. TLS, startup, and cleanup

The first job script reads the allocated node list, then invokes:

```bash
python3 scripts/make_cert.py --out RESULTS_DIRECTORY/certs --host RELAY_HOSTNAME
```

This creates `cert.pem` and `key.pem` for the allocated relay hostname. All clients verify the certificate using that run's certificate file as their TLS root. The job creates private result directories and uses a new certificate for each run; it does not disable TLS verification. A hostname mismatch is a configuration error to fix, not a reason to silently turn verification off.

The relay CLI requires a numeric bind address, so the worker resolves the allocated relay hostname to IPv4 for `--bind`. Clients use the original DNS name in `moqt://HOST:4443`. If ICE's selected interface cannot carry these connections, inspect the recorded addresses/routes and test the permitted node-to-node path. An advertised InfiniBand speed is not evidence of the actual QUIC path or its throughput.

The workers wait for relay metrics, then for the publisher's own accepted-track `ready` event, before starting subscribers. A publisher-count metric alone is not used as evidence that publishing was accepted. Readiness waits time out after 90 seconds. A fresh per-job coordinator file avoids interference from another relay's `/tmp` state. Each generator must exit successfully and provide `ready` and `complete` events for exactly its assigned client IDs before it is marked done. When both generators finish, the publisher and relay stop. Slurm terminates the other workers if one fails. Workers handle termination by stopping their child process and copying logs from node-local temporary storage into the shared results directory. An abrupt node failure or forced kill may prevent that final copy; absence of logs is not a successful run.

## 5. Find the output and check success

For job `12345`, inspect `logs/ice-12345.out` and `results/ice-12345/`:

```bash
sacct -j 12345 --format=JobID,State,Elapsed,ExitCode,MaxRSS
```

Replace `12345` with the real job ID. Use `scancel 12345` only when you intend to stop that job.

Each role writes:

- `metadata.json`: hardware/software/allocation information and workload parameters.
- `worker.jsonl`: orchestration events and exact child commands.
- `process.jsonl`: approximately one-second samples of the child process's resident memory and cumulative CPU seconds, using the same sampler as the local runner.
- `stdout.jsonl`: the load program's original JSONL output; the relay may leave this empty.
- `stderr.log`: diagnostic messages, including the stock relay's text logs.

The relay also writes `metrics.jsonl`, containing timestamped Prometheus snapshots. Top-level files record commits, dirty-checkout status, allocated nodes, allocation details, and readiness/completion markers. A `*.failed.json` file explains a worker failure. Check received Objects as well as readiness/completion and Slurm's exit code: a successfully running process is not sufficient evidence that useful media was delivered. Slurm's `MaxRSS` is a coarse job-step metric. The one-second process samples can also miss short peaks; neither measure isolates Object-cache memory.

Export the raw outputs before analysis and retain the exact configuration used. Keep `certs/key.pem` private and exclude it from shared report artifacts. Cross-node latency needs clock-offset checks; `chronyc tracking` is recorded where available, but a successful command alone does not establish sufficiently synchronized clocks. Do not subtract timestamps from unrelated monotonic clocks on different machines.

## What this experiment can claim

This launcher runs the stock pinned relay and the native publisher/subscriber load generator. It does not implement the proposed adaptive scheduling policy or impose a physical-link bottleneck. Controlled read stalls exercise subscriber backpressure; they do not reproduce a lossy mobile network. Later application rate gates should be identical across comparison policies and should not introduce their own fairness decisions. Root privileges, `tc`, and Docker are not assumed or required by these scripts.

Label laptop runs as local preliminary measurements. Label these files as prepared ICE scripts until a completed ICE job supplies logs. Report the actual allocated hardware and measured path, not a guessed server specification or results inferred from successful submission.

## Sources and verification status

Reviewed November 10, 2026. The [GT teaching page](https://sites.gatech.edu/higheducation2024/tutorial/) links to the ICE job and storage articles above. Both ServiceNow article URLs were inaccessible through the documentation-fetch tool, so their current contents and account-specific limits were **not** independently verified. Open them through your normal GT sign-in if necessary.

The launch structure follows the [official Slurm sbatch documentation](https://slurm.schedmd.com/sbatch.html), [srun documentation](https://slurm.schedmd.com/srun.html), and [Slurm environment-variable reference](https://slurm.schedmd.com/pdfs/summary.pdf). Relay flags and the metrics feature were checked against the pinned source in `vendor/moq-rs/moq-relay-ietf/src/bin/moq-relay-ietf/main.rs` and `vendor/moq-rs/moq-native-ietf/src/tls.rs`.
