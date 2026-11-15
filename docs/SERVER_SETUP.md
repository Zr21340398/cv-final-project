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

## 4. 在登录节点配置模块

你现在的 `login1` 是登录节点，默认 Python 3.9 和找不到 GPU 工具都可能出现。先在登录节点查看学校当前可用模块，不申请 GPU：

```bash
source /opt/shared/.spack-edge/dist/bin/setup-env.sh
module spider python
module spider cuda
```

选择 **Python 3.10 或 3.11** 和 **CUDA toolkit 12.4**。如果 `module spider` 提示需要先加载编译器或其他模块，按它给出的顺序填写。学校模块名称以实际输出为准。

```bash
cd ~/project/cv-final-project
mkdir -p local logs
cp -n configs/hpc4_modules.example.sh local/hpc4_modules.sh
nano local/hpc4_modules.sh
```

在编辑器中，删除示例文件最后的 `echo` 和 `return 1` 两行，将 `module load` 注释替换成学校实际的模块名称，例如根据实际输出填写前置模块、Python 模块和 CUDA 模块，按 Ctrl+O 保存、Enter 确认、Ctrl+X 退出。`local/` 不提交到 Git。可以先在当前终端手动执行相同的 `module load` 命令并检查 `python3 --version` 和 `nvcc --version`；作业仍会独立加载这些模块。

## 5. 提交自动安装作业

TRELLIS.2 环境、CUDA 扩展、DINOv3 与模型权重由一个 GPU 作业顺序完成。作业中会自动重建模块环境；请先在 Hugging Face 的 RMBG-2.0 页面接受访问条款，并在本机或服务器使用有访问权限的账号准备好可供作业读取的登录状态。若使用 `HF_TOKEN` 环境变量，提交前在当前终端安全设置并 `export`，提交后在终端 `unset HF_TOKEN`；不要把 token 写入脚本或仓库。

在登录节点、项目根目录执行：

```bash
cd ~/project/cv-final-project
mkdir -p logs
export HF_HOME="$PWD/models/huggingface"
export ASSET3D_DINOV3_DIR="$PWD/models/dinov3-vitl16-pretrain-lvd1689m"
sbatch slurm/install_trellis2.sbatch
```

例如返回 `Submitted batch job 123456`，数字就是作业号。系统排到 L20 后自动执行；你无需等待在终端输入后续命令。学校说明参见 [Slurm 快速入门](https://hkust-hpc-docs.readthedocs.io/latest/quick-start/index.html)。

```bash
squeue -u "$USER"
tail -f logs/trellis2-install-<作业号>.out
```

把 `<作业号>` 换成实际数字；按 Ctrl+C 只停止查看日志。`squeue` 为空时用下列命令查看最终状态：

```bash
sacct -j <作业号> --format=JobID,State,ExitCode,Elapsed
```

`COMPLETED`、`ExitCode 0:0` 且日志最后有“安装和检查完成”，表示这次作业的安装和检查完成。`FAILED`、`TIMEOUT` 或其他状态需要查看日志中最后的错误。这个作业尚未在你的账户实测；需要 GPU 节点能访问软件和模型下载源，网络受限、磁盘不足或模型未授权时会停在对应阶段。默认申请一张 L20、4 CPU、32 GiB 内存和 4 小时时限；计费和可用性以学校设置为准。

失败后先查看日志，排除网络、权限或模块错误，再重新提交。脚本会核对已有第三方源码版本并复用已有虚拟环境、缓存文件；若之前的 Git 仓库下载中断，可能需要先修复不完整的第三方目录，不要盲目覆盖或删除。安装完成后按 [TRELLIS.2 实验指南](TRELLIS2_GSO_DEV_GUIDE.md) 运行检查和实验。推理作业也会读取 `local/hpc4_modules.sh`。

混元环境使用独立 `.venv-hpc`；若之后需要安装混元，继续使用 `scripts/install_hpc.sh` 并在对应模型环境中执行 `asset3d download --config configs/hunyuan2_pilot_retry.yaml --background`。当前自动安装作业只负责 TRELLIS.2。

## 6. 数据检查

在已安装本项目的 Python 环境、仓库根目录执行：

```bash
python scripts/run_batch.py experiments/trellis2-gso-dev-v1/batch.yaml --prepare-only
```

只读取本批次选中的 10 个对象，不启动 GPU。输入和参考网格核验通过后，按对应批次指南提交作业。
