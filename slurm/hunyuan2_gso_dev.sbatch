#!/usr/bin/env bash
#SBATCH --job-name=hunyuan2-gso-dev
#SBATCH --account=mscaiehpc42026
#SBATCH --partition=gpu-l20
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --time=04:00:00
#SBATCH --output=logs/%x-%j.out

set -euo pipefail
: "${SLURM_SUBMIT_DIR:?请在项目根目录提交作业}"
cd "$SLURM_SUBMIT_DIR"
# 两个模型的环境独立；避免意外使用混元依赖。
export ASSET3D_VENV="${HUNYUAN2_VENV:-$SLURM_SUBMIT_DIR/.venv-hpc}"
source slurm/common.sh
BATCH="${1:-experiments/hunyuan2-gso-dev-rerun/batch.yaml}"
python scripts/run_batch.py "$BATCH" --backend hunyuan2 --prepare-only
asset3d doctor --gpu --backend hunyuan2 --output "logs/doctor-hunyuan2-$SLURM_JOB_ID.json"
# 固定开发集、模型配置和两个种子；续跑时核验冻结计划和源码指纹。
python scripts/run_batch.py "$BATCH" --backend hunyuan2
