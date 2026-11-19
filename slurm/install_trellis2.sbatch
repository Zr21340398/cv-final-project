#!/usr/bin/env bash
#SBATCH --job-name=trellis2-install
#SBATCH --account=mscaiehpc42026
#SBATCH --partition=gpu-l20
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=logs/%x-%j.out

# 由 Slurm 等待 GPU；从仓库根目录提交，日志目录需要事先创建。
set -Eeuo pipefail
trap 'echo "安装失败：请检查上方日志，阶段=${stage:-初始化}" >&2' ERR
: "${SLURM_SUBMIT_DIR:?请从项目根目录提交作业}"
cd "$SLURM_SUBMIT_DIR"
stage=模块配置
# 后续推理作业也使用同一份配置。
source slurm/load_hpc4_modules.sh
# 禁止继续使用登录节点的 Python 3.9；先确认工具再进行耗时安装。
python3 -c 'import sys; assert sys.version_info[:2] in [(3,10),(3,11)], "Python 需要 3.10 或 3.11"'
command -v nvcc >/dev/null || { echo '未找到 nvcc，请检查 CUDA 模块。' >&2; exit 1; }
nvcc --version | grep -q 'release 12.4' || { echo '需要 CUDA toolkit 12.4。' >&2; exit 1; }
nvidia-smi
export HF_HOME="${HF_HOME:-$SLURM_SUBMIT_DIR/models/huggingface}"
export ASSET3D_DINOV3_DIR="${ASSET3D_DINOV3_DIR:-$SLURM_SUBMIT_DIR/models/dinov3-vitl16-pretrain-lvd1689m}"
export MAX_JOBS="${MAX_JOBS:-2}"
export PYTHONUNBUFFERED=1
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE
mkdir -p "$HF_HOME" "$ASSET3D_DINOV3_DIR"
echo "安装作业运行在 $(hostname)，模型缓存：$HF_HOME"
stage=环境与CUDA扩展
bash scripts/install_trellis2_hpc.sh
source "${TRELLIS2_VENV:-$SLURM_SUBMIT_DIR/.venv-trellis2}/bin/activate"
stage=DINOv3下载
python -m pip install modelscope
python - <<'PY'
import os
from modelscope import snapshot_download
snapshot_download("facebook/dinov3-vitl16-pretrain-lvd1689m", local_dir=os.environ["ASSET3D_DINOV3_DIR"])
PY
stage=主模型和辅助权重下载
asset3d download --config configs/trellis2_gso_dev.yaml
stage=离线权重与GPU检查
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python - <<'PY'
from asset3d.backends.trellis2 import snapshot
from asset3d.config import load_config
snapshot(load_config("configs/trellis2_gso_dev.yaml")["model"], download=False)
print("固定版本模型和 DINOv3 检查完成。")
PY
asset3d doctor --gpu --backend trellis2 --output "logs/doctor-trellis2-install-$SLURM_JOB_ID.json"
echo '安装和检查完成；接下来提交单例或实验批次。'
