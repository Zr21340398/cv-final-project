#!/usr/bin/env bash
#SBATCH --job-name=trellis2-front
#SBATCH --account=mscaiehpc42026
#SBATCH --partition=gpu-l20
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out

set -euo pipefail
: "${SLURM_SUBMIT_DIR:?请在项目根目录提交}"
cd "$SLURM_SUBMIT_DIR"
source slurm/load_hpc4_modules.sh
export ASSET3D_VENV="${TRELLIS2_VENV:-$PWD/.venv-trellis2}"
export HF_HOME="${HF_HOME:-$PWD/models/huggingface}"
export ASSET3D_DINOV3_DIR="${ASSET3D_DINOV3_DIR:-$PWD/models/dinov3-vitl16-pretrain-lvd1689m}"
source slurm/common.sh
python scripts/rerun_trellis2_front.py
