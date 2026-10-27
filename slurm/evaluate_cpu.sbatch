#!/usr/bin/env bash
#SBATCH --job-name=asset3d-evaluate
#SBATCH --account=mscaiehpc42026
#SBATCH --partition=amd
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail
source "$SLURM_SUBMIT_DIR/slurm/common.sh"
: "${1:?Usage: sbatch slurm/evaluate_cpu.sbatch results_directory [rigid_transform.json]}"
args=()
if [[ -n "${2:-}" ]]; then args+=(--transform "$2"); fi
asset3d evaluate-batch --experiment "$1" "${args[@]}"
asset3d summarize --experiment "$1" --output "$1/summary"

