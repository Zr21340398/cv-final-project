# 数据与模型权重的统一准备方法

服务器仓库根目录固定为 `~/project/cv-final-project/`。代码通过 Git 获取，GSO 数据和模型权重各准备一次，后续批次按路径复用。本指南不使用本地压缩包，也不要求把数据或权重提交到 Git。

## 1. 获取代码

服务器登录节点首次执行：

```bash
mkdir -p ~/project
cd ~/project
git clone --branch trellis2-gso-dev --single-branch https://github.com/Zr21340398/cv-final-project.git
cd cv-final-project
mkdir -p datasets/gso-v1 models logs
```

已有仓库进入该目录执行 `git pull`，无需再次克隆。

## 2. GSO：原始下载与本实验输入

原始 GSO 对象的下载地址、对象 ID、许可和来源见 `data/manifests/gso-selection.csv` 及同目录的 metadata JSON。可从这些对象对应的下载地址获取原始网格和材质，保存在 `datasets/gso-v1/data/raw/`。原始网格还需要按实验视角和归一化规则渲染，才能形成当前使用的输入。

本机已经准备好一套固定视角图片和参考模型，现已集中在 `datasets/gso-v1/data/`。为了与已完成混元实验使用完全相同的数据，首次把这一目录传到服务器即可；目前没有为这套处理后数据提供公开下载地址。

在笔记本 PowerShell 中执行：

```powershell
Set-Location 'D:\AIEproject\MAIE5421_CV\Final Project'
scp -r .\datasets\gso-v1\data hkust-hpc4:~/project/cv-final-project/datasets/gso-v1/
```

先执行第 1 节创建服务器目标目录。`hkust-hpc4` 使用你的实际 SSH 别名。只需传一次；后续实验直接引用共享清单，不再为每批复制 data。完整目录还包含 raw、相机记录等来源信息，可继续用于扩展实验。

服务器目录应为：

```text
datasets/gso-v1/data/
  manifests/gso-formal-v1.csv    30 个对象
  manifests/gso-dev-v1.csv       10 个开发对象
  raw/                          原始扫描文件
  rendered/gso-formal-v1/        固定视角 PNG 与参考 GLB
```

若服务器已有同样数据，可将现有 data 目录放到该位置，先比较同名文件再处理冲突。不要把 data 再套在另一个 data 里面。新机器上的批次准备会核验所选对象的文件哈希，发现差异即停止。

## 3. 共享权重目录

下载权重和提交作业的终端都使用以下设置：

```bash
cd ~/project/cv-final-project
export HF_HOME="$PWD/models/huggingface"
export U2NET_HOME="$PWD/models/rembg"
export ASSET3D_DINOV3_DIR="$PWD/models/dinov3-vitl16-pretrain-lvd1689m"
mkdir -p "$HF_HOME" "$U2NET_HOME"
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE
```

如果个人目录配额不足，可以将这些变量设为自己的 scratch 路径。每次下载和运行使用相同路径；权重不随实验复制。`models/` 已被 Git 忽略。

## 4. 首次环境安装

### GPU 环境

登录节点申请一张 L20：

```bash
srun --account=mscaiehpc42026 --partition=gpu-l20 --nodes=1 --ntasks=1 --gpus-per-node=1 --time=02:00:00 --pty bash
```

在计算节点按学校当前模块列表加载 Python 3.10 或 3.11、CUDA 12.4 及编译工具。先检查：

```bash
cd ~/project/cv-final-project
python3 --version
nvcc --version
nvidia-smi
```

TRELLIS.2 执行：

```bash
bash scripts/install_trellis2_hpc.sh
source .venv-trellis2/bin/activate
asset3d doctor --gpu --backend trellis2
```

混元执行：

```bash
bash scripts/install_hpc.sh
source .venv-hpc/bin/activate
asset3d doctor --gpu --backend hunyuan2
```

两个环境分别保存，第三方 CUDA 扩展位于被 Git 忽略的 `third_party/`。安装需要网络与编译时间，失败时保存完整日志。学校模块与账户问题请查看学校 HPC4 文档，或联系 HPC4 支持。下载和作业应使用相同缓存路径。长时间等权限或查资料时退出 GPU 分配。


## 5. 下载模型权重

请先完成上一节的 GPU 环境安装。以下下载命令在已激活的相应环境中运行。下载需联网；GPU 推理作业使用离线缓存。

### TRELLIS.2

先激活 `.venv-trellis2`。固定适配器使用本地 DINOv3 ViT-L/16，其下载来源为魔搭，文件内容由适配器中的 SHA-256 检查：

```bash
source .venv-trellis2/bin/activate
python -m pip install modelscope
python - <<'PY'
import os
from modelscope import snapshot_download
snapshot_download('facebook/dinov3-vitl16-pretrain-lvd1689m', local_dir=os.environ['ASSET3D_DINOV3_DIR'])
PY
```

该目录应包含 `config.json`、`preprocessor_config.json`、`model.safetensors`。当前适配器要求的权重 SHA-256 是 `dcb2e45127cccbf1601e5f42fef165eea275c8e5213197e8dcf3f48822718179`；如果上游下载内容变化，程序会提示不匹配，应核对版本。

辅助模型 RMBG-2.0 需要在其 Hugging Face 页面完成访问授权。遇到 401/403，先在同一个缓存设置下登录有权限的账户，例如环境提供 `hf` 命令时运行 `hf auth login`。不要把 token 写进仓库。

```bash
asset3d download --config configs/trellis2_gso_dev.yaml
```

此命令下载固定版本的 TRELLIS.2 主模型、稀疏结构解码器、背景模型，并读取已准备好的 DINOv3。完成后可以退出下载节点。

### 混元 3D 2.0

```bash
source .venv-hpc/bin/activate
asset3d download --config configs/hunyuan2_pilot_retry.yaml --background
```

该命令下载固定版本的形状、上色、去光照权重，以及背景处理模型。两个模型共用缓存目录结构，使用不同权重文件与 Python 环境。

## 6. 数据检查

在已安装本项目的 Python 环境、仓库根目录执行：

```bash
python scripts/run_batch.py experiments/trellis2-gso-dev-v1/batch.yaml --prepare-only
```

只读取本批次选中的 10 个对象，不启动 GPU。输入和参考网格核验通过后，按对应批次指南提交作业。
