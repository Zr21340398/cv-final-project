#!/usr/bin/env bash
#SBATCH --job-name=asset3d-smoke
#SBATCH --account=mscaiehpc42026
#SBATCH --partition=gpu-l20
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail
source "$SLURM_SUBMIT_DIR/slurm/common.sh"
: "${1:?Usage: sbatch slurm/smoke.sbatch image_path [output_directory]}"
asset3d doctor --gpu --output "logs/doctor-$SLURM_JOB_ID.json"
asset3d generate --image "$1" --config configs/baseline.yaml --seed 42 --output "${2:-results/smoke-$SLURM_JOB_ID}"

