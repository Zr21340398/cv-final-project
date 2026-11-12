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
: "${1:?Usage: sbatch slurm/evaluate_cpu.sbatch results_directory [rigid_transform.json] [shape_raw.glb|asset.glb]}"
args=()
if [[ -n "${2:-}" ]]; then args+=(--transform "$2"); fi
if [[ -n "${3:-}" ]]; then args+=(--artifact "$3"); fi
status=0
asset3d evaluate-batch --experiment "$1" "${args[@]}" || status=$?
# Keep the full success/failure denominator even when a metric calculation fails.
asset3d summarize --experiment "$1" --output "$1/summary"
exit "$status"

