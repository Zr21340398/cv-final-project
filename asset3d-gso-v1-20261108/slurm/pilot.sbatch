#!/usr/bin/env bash
#SBATCH --job-name=asset3d-pilot
#SBATCH --account=mscaiehpc42026
#SBATCH --partition=gpu-l20
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out

# 上方申请一张 L20 和两小时时限；作业排到资源后才会执行下方命令。
set -euo pipefail
: "${SLURM_SUBMIT_DIR:?Submit from project root}"
cd "$SLURM_SUBMIT_DIR"
: "${1:?Usage: sbatch slurm/pilot.sbatch trellis2|hunyuan2 experiment_dir [extra pilot-run options]}"
: "${2:?Missing experiment directory}"
MODEL="$1"
EXPERIMENT="$2"
shift 2
# 根据模型选择独立 Python 环境，避免两套官方依赖互相影响。
case "$MODEL" in
  trellis2) export ASSET3D_VENV="${TRELLIS2_VENV:-$SLURM_SUBMIT_DIR/.venv-trellis2}" ;;
  hunyuan2) export ASSET3D_VENV="${HUNYUAN2_VENV:-$SLURM_SUBMIT_DIR/.venv-hpc}" ;;
  *) echo 'Model must be trellis2 or hunyuan2'; exit 1 ;;
esac
# 载入缓存路径和环境设置，先检查 GPU，再运行指定实验组。
source slurm/common.sh
asset3d doctor --gpu --backend "$MODEL" --output "logs/doctor-$MODEL-$SLURM_JOB_ID.json"
asset3d pilot-run --experiment "$EXPERIMENT" --name "$MODEL" "$@"
