#!/usr/bin/env bash
# Run on an allocated HPC4 compute node. Load a CUDA 12.4 toolkit first.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
: "${SLURM_JOB_ID:?Run inside a Slurm compute allocation, not the login node}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ENV_DIR="${ASSET3D_VENV:-$ROOT/.venv-hpc}"
command -v nvcc >/dev/null || { echo 'CUDA toolkit nvcc is missing. Inspect module avail and load CUDA 12.4.'; exit 1; }
nvcc --version | grep -q 'release 12.4' || { echo 'This candidate environment expects CUDA toolkit 12.4; do not mix toolkits silently.'; exit 1; }
"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] in [(3,10),(3,11)], "Use Python 3.10 or 3.11"'
if [[ ! -d "$ENV_DIR" ]]; then "$PYTHON_BIN" -m venv "$ENV_DIR"; fi
source "$ENV_DIR/bin/activate"
python -m pip install 'pip<26' 'setuptools<76' wheel
python -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
python -m pip install -r requirements-hpc.txt
REVISION=f8db63096c8282cb27354314d896feba5ba6ff8a
UPSTREAM="$ROOT/third_party/Hunyuan3D-2"
if [[ ! -e "$UPSTREAM" ]]; then
  mkdir -p "$ROOT/third_party"
  git init "$UPSTREAM"
  git -C "$UPSTREAM" remote add origin https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git
  git -C "$UPSTREAM" fetch --depth 1 origin "$REVISION"
  git -C "$UPSTREAM" checkout --detach FETCH_HEAD
fi
[[ "$(git -C "$UPSTREAM" rev-parse HEAD)" == "$REVISION" ]] || { echo 'Existing upstream revision differs; refusing to reset it.'; exit 1; }
[[ -z "$(git -C "$UPSTREAM" status --porcelain --untracked-files=no)" ]] || { echo 'Upstream has modifications; refusing to overwrite.'; exit 1; }
python -m pip install --no-deps --no-build-isolation -e "$UPSTREAM"
export MAX_JOBS="${MAX_JOBS:-2}"
python -m pip install --no-deps --no-build-isolation "$UPSTREAM/hy3dgen/texgen/custom_rasterizer"
python -m pip install --no-deps --no-build-isolation "$UPSTREAM/hy3dgen/texgen/differentiable_renderer"
python -m pip install --no-deps -e "$ROOT"
python -m pip check
mkdir -p logs
python -m pip freeze > logs/environment-hpc.freeze.txt
python -m asset3d.cli doctor --gpu --output logs/environment-hpc.json
echo 'Environment installed. Next explicitly download weights with asset3d download --background.'

