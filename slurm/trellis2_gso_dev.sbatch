#!/usr/bin/env bash
#SBATCH --job-name=trellis2-gso-dev
#SBATCH --account=mscaiehpc42026
#SBATCH --partition=gpu-l20
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --time=04:00:00
#SBATCH --output=logs/%x-%j.out

set -euo pipefail
: "${SLURM_SUBMIT_DIR:?请在项目根目录提交作业}"
: "${1:?用法: sbatch slurm/trellis2_gso_dev.sbatch 数据清单.csv 结果目录}"
: "${2:?请提供独立的结果目录}"
cd "$SLURM_SUBMIT_DIR"
# 两个模型的环境独立；避免意外使用混元依赖。
export ASSET3D_VENV="${TRELLIS2_VENV:-$SLURM_SUBMIT_DIR/.venv-trellis2}"
source slurm/common.sh
python scripts/check_trellis2_gso_dev.py "$1"
asset3d doctor --gpu --backend trellis2 --output "logs/doctor-trellis2-$SLURM_JOB_ID.json"
# 固定开发集、模型配置和两个种子；续跑时核验冻结计划和源码指纹。
asset3d batch --manifest "$1" --configs configs/trellis2_gso_dev.yaml \
  --split dev --seeds 42 123 --output "$2" --resume
