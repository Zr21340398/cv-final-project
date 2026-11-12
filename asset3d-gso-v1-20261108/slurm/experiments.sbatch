#!/usr/bin/env bash
#SBATCH --job-name=asset3d-experiment
#SBATCH --account=mscaiehpc42026
#SBATCH --partition=gpu-l20
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail
: "${SLURM_SUBMIT_DIR:?Submit from the project root}"
cd "$SLURM_SUBMIT_DIR"
: "${1:?Usage: sbatch slurm/experiments.sbatch manifest.csv results_directory [formal-run options]}"
: "${2:?An explicit results directory is required}"
# Optional account-local CUDA/module/cache setup, never committed to the repo.
if [[ -f configs/hpc4-session.local.sh ]]; then source configs/hpc4-session.local.sh; fi
source slurm/common.sh
manifest="$1"
output="$2"
shift 2
# The CPU dry run checks dataset readiness and frozen identities before model loading.
asset3d formal-run --manifest "$manifest" --output "$output" "$@" --dry-run
asset3d doctor --gpu --backend hunyuan2 --output "logs/doctor-formal-$SLURM_JOB_ID.json"
asset3d formal-run --manifest "$manifest" --output "$output" "$@"

