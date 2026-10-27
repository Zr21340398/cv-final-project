#!/usr/bin/env bash
# 在已申请的 GPU 节点安装独立环境；依赖保存在项目目录，使用普通用户权限。
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
: "${SLURM_JOB_ID:?Run inside a Slurm GPU allocation}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ENV_DIR="${TRELLIS2_VENV:-$ROOT/.venv-trellis2}"
# 编译 CUDA 扩展需要开发工具包；这里检查实际使用的 nvcc 版本。
command -v nvcc >/dev/null || { echo 'Load the CUDA 12.4 toolkit first'; exit 1; }
nvcc --version | grep -q 'release 12.4' || { echo 'Expected CUDA toolkit 12.4'; exit 1; }
"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] in [(3,10),(3,11)]'
# 只在 TRELLIS.2 的虚拟环境里安装依赖，混元使用另一套环境。
if [[ ! -d "$ENV_DIR" ]]; then "$PYTHON_BIN" -m venv "$ENV_DIR"; fi
source "$ENV_DIR/bin/activate"
python -m pip install 'pip<26' 'setuptools<76' wheel packaging
python -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
python -m pip install -r requirements-trellis2.txt
export MAX_JOBS="${MAX_JOBS:-2}"
# 每个第三方仓库固定到具体提交，后续运行可核对使用的代码版本。
checkout() {
  local name="$1" url="$2" revision="$3"
  local dest="$ROOT/third_party/$name"
  if [[ ! -e "$dest" ]]; then
    mkdir -p "$ROOT/third_party"
    git init "$dest"
    git -C "$dest" remote add origin "$url"
    git -C "$dest" fetch --depth 1 origin "$revision"
    git -C "$dest" checkout --detach FETCH_HEAD
    git -C "$dest" submodule update --init --recursive
  fi
  [[ "$(git -C "$dest" rev-parse HEAD)" == "$revision" ]] || { echo "Wrong revision: $dest"; exit 1; }
  [[ -z "$(git -C "$dest" status --porcelain --untracked-files=no)" ]] || { echo "Modified source: $dest"; exit 1; }
}
checkout TRELLIS.2 https://github.com/microsoft/TRELLIS.2.git 75fbf0183001ed9876c8dbb35de6b68552ee08bd
checkout CuMesh https://github.com/JeffreyXiang/CuMesh.git 12289e1062f0603f2f0d0771b02e1395d247f26f
checkout FlexGEMM https://github.com/JeffreyXiang/FlexGEMM.git 6dd94a859c26ee8246888502eada3dd8ad85532e
checkout nvdiffrast-trellis2 https://github.com/NVlabs/nvdiffrast.git 253ac4fcea7de5f396371124af597e6cc957bfae
checkout nvdiffrec-trellis2 https://github.com/JeffreyXiang/nvdiffrec.git b296927cc7fd01c2ac1087c8065c4d7248f72da4
checkout utils3d-trellis2 https://github.com/EasternJournalist/utils3d.git 9a4eb15e4021b67b12c460c7057d642626897ec8
python -m pip install "$ROOT/third_party/utils3d-trellis2"
# 编译注意力、网格处理和渲染扩展；这一步可能比普通 Python 包安装耗时更长。
python -m pip install flash-attn==2.7.3 --no-build-isolation
for name in CuMesh FlexGEMM nvdiffrast-trellis2 nvdiffrec-trellis2; do
  python -m pip install --no-build-isolation "$ROOT/third_party/$name"
done
python -m pip install --no-build-isolation "$ROOT/third_party/TRELLIS.2/o-voxel"
# 官方仓库通过源码目录导入；用 .pth 文件将该目录加入当前环境的模块搜索路径。
export TRELLIS2_SOURCE="$ROOT/third_party/TRELLIS.2"
python -c 'import os,site,pathlib; (pathlib.Path(site.getsitepackages()[0])/"trellis2-source.pth").write_text(os.environ["TRELLIS2_SOURCE"]+"\n")'
python -m pip install --no-deps -e "$ROOT"
python -m pip check
mkdir -p logs
# 保存真实安装版本并检查 GPU，方便后续复现和排查安装问题。
python -m pip freeze > logs/environment-trellis2.freeze.txt
python -m asset3d.cli doctor --gpu --backend trellis2 --output logs/environment-trellis2.json
echo 'Candidate environment installed. Download pinned weights before offline jobs; see docs/PILOT_GUIDE.md.'
