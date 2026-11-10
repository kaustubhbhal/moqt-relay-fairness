#!/usr/bin/env bash
#SBATCH --job-name=moqt-ice
#SBATCH --nodes=4
#SBATCH --ntasks=4
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --output=logs/ice-%j.out

# Submit from the repository root after: mkdir -p logs
# Account/partition/QOS are intentionally left to the user's ICE defaults.
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
umask 077
export MOQT_RUN_DIR="$SLURM_SUBMIT_DIR/results/ice-$SLURM_JOB_ID"
mkdir "$MOQT_RUN_DIR"
scontrol show hostnames "$SLURM_JOB_NODELIST" > "$MOQT_RUN_DIR/nodes.txt"
relay_host=$(head -n 1 "$MOQT_RUN_DIR/nodes.txt")
python3 scripts/make_cert.py --out "$MOQT_RUN_DIR/certs" --host "$relay_host"
git rev-parse HEAD > "$MOQT_RUN_DIR/commit.txt"
git status --short > "$MOQT_RUN_DIR/git-status.txt"
git -C vendor/moq-rs rev-parse HEAD > "$MOQT_RUN_DIR/relay-commit.txt"
scontrol show job "$SLURM_JOB_ID" > "$MOQT_RUN_DIR/allocation.txt"

# Single srun step avoids concurrent steps competing for allocated CPUs.
# Every worker is bounded and cleans up its own child process on SIGTERM.
srun --mpi=none --cpu-bind=cores --kill-on-bad-exit=1 \
  python3 scripts/ice_worker.py
