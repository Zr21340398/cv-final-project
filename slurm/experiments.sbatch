#!/usr/bin/env bash
#SBATCH --job-name=asset3d-experiment
#SBATCH --account=mscaiehpc42026
#SBATCH --partition=gpu-l20
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail
source "$SLURM_SUBMIT_DIR/slurm/common.sh"
: "${1:?Usage: sbatch slurm/experiments.sbatch manifest.csv results_directory}"
: "${2:?An explicit results directory is required}"
asset3d batch --manifest "$1" --output "$2" --split test --seeds 42 123 --resume

