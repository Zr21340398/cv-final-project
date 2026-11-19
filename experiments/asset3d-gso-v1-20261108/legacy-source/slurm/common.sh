#!/usr/bin/env bash
set -euo pipefail
: "${SLURM_SUBMIT_DIR:?Submit this job through sbatch from the project root}"
cd "$SLURM_SUBMIT_DIR"
ENV_DIR="${ASSET3D_VENV:-$SLURM_SUBMIT_DIR/.venv-hpc}"
source "$ENV_DIR/bin/activate"
# A reused virtualenv may have an editable install pointing at an older project.
# Always import this submitted snapshot, including in per-sample child processes.
export PYTHONPATH="$SLURM_SUBMIT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
export HF_HOME="${HF_HOME:-/scratch/$USER/project3/cache/huggingface}"
export U2NET_HOME="${U2NET_HOME:-/scratch/$USER/project3/cache/rembg}"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-2}"
mkdir -p "$HF_HOME" "$U2NET_HOME"
# Fail rather than silently downloading during a paid generation job.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONUNBUFFERED=1

