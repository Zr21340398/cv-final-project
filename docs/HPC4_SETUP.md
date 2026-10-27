# HPC4：从现有 SSH/Tunnel 连接到首次生成

本指南面向 `rzhoubf` / `mscaiehpc42026`。本次代码生成没有登录服务器、安装远程软件、下载权重或提交付费任务。下列操作在你准备运行时执行。

## 1. 将代码放到服务器

本地已生成 `dist/asset3d-source.tar.gz`，也可在项目目录重新打包：

```powershell
.\.venv\Scripts\python.exe scripts/package_project.py
scp "D:\AIEproject\MAIE5421_CV\Final Project\dist\asset3d-source.tar.gz" hkust-hpc4:~/
ssh hkust-hpc4
```

下面开始是 Linux/HPC 命令。在 home 解包得到 `~/asset3d`。如果已有同名项目，应先检查，不覆盖自己的修改：

```bash
test ! -e ~/asset3d && tar -xzf ~/asset3d-source.tar.gz -C ~
cd ~/asset3d
mkdir -p logs
```

已有项目更新应比较变更后同步代码，不要复制笔记本的 `.venv` 到 Linux。

## 2. 先检查学校环境

```bash
srun --account=mscaiehpc42026 --partition=gpu-l20 --nodes=1 --gpus-per-node=1 --time=01:00:00 --pty bash
nvidia-smi
module avail
python3 --version
command -v nvcc
```

在分配到的计算节点上安装/编译与运行模型。首次安装脚本使用候选组合 Python 3.10/3.11 + PyTorch 2.5.1/cu124 + CUDA toolkit 12.4；**该组合尚未在你们 HPC4 上实测**。根据 `module avail` 找到对应 CUDA 模块并加载，具体模块名不猜测。驱动支持的 CUDA 版本和 `nvcc` 工具链版本不是同一个信息。

如果学校没有 CUDA 12.4 工具链，先记录现有版本，再统一调整 PyTorch wheel、torchvision 与 toolkit；不要跳过版本检查强行混装。没有管理员权限也可以使用学校模块与个人虚拟环境，不需要安装系统级驱动。

## 3. 安装到个人虚拟环境

在项目根目录、计算节点执行：

```bash
export HF_HOME=/scratch/$USER/project3/cache/huggingface
export U2NET_HOME=/scratch/$USER/project3/cache/rembg
export MAX_JOBS=2
bash scripts/install_hpc.sh
source .venv-hpc/bin/activate
```

脚本检查 Slurm 分配和 CUDA 12.4，安装候选依赖，获取锁定的官方代码，编译纹理扩展，执行依赖检查，保存 `logs/environment-hpc.freeze.txt` 和 `logs/environment-hpc.json`。学校可用模块/系统库不同可能需要调整；这些记录用于排错，只有实际跑通后才能称为验证过的 HPC 环境。

编译期间如果出现 `libGL`、编译器、CUDA mismatch 等错误，保留完整输出。脚本不会用 sudo，也不会重置已有上游修改。重试安装前应确认前次安装进程已经结束。

## 4. 单独下载权重

保持上一步两个缓存变量相同，执行：

```bash
asset3d download --config configs/baseline.yaml --background
```

这一步明确下载固定 revision 的几何、纹理、去光照权重，以及背景去除模型。下载可在学校允许联网的非 GPU 环境完成；如果切回登录节点，先激活虚拟环境并保持缓存变量。网络下载无需 GPU，不应为下载长时间占住显卡。若计算节点无外网，按学校提供的下载/传输方式预先准备缓存。

`configs/baseline.yaml` 默认 `local_files_only: true`；正式任务不应临时下载大文件。缓存位于 scratch，需考虑学校 60 天不活跃文件清理规则；长期归档存到组内约定的 project 子目录。

## 5. 首个真实样例

准备一张清晰、单个物体的图片，放到 `data/raw/object.png`。也可使用安装后的官方示例图片，但先确认实际文件位置。

已在 GPU 交互节点时，直接运行，不要再嵌套申请 GPU：

```bash
asset3d generate --image data/raw/object.png --output results/first --seed 42
```

或退出交互分配、回到登录节点后提交：

```bash
mkdir -p logs
sbatch slurm/smoke.sbatch data/raw/object.png
squeue -u "$USER"
```

Slurm 日志在 `logs/asset3d-smoke-JOBID.out`。必须在提交前创建 logs，因为 Slurm 在脚本执行前就打开输出文件。首次任务设置了 30 分钟上限；后续按真实样例的耗时调整申请时长。

完成后将 `asset.glb` 下载到笔记本，在 Blender 或界面里确认纹理与多视角，再进行大规模实验。

## 6. VS Code 中使用界面

Tunnel 必须启动在已经分配的计算节点。进入项目目录并激活环境，然后：

```bash
python -m asset3d.demo
```

在 VS Code 的 Ports 面板添加 7860，保持私有访问，然后打开本地转发地址。界面必须运行在有 GPU 的计算节点；CPU 节点只能验证界面能打开，不能运行生成。

## 7. 实验与恢复

```bash
sbatch slurm/experiments.sbatch data/manifests/objects.csv results/experiment01
```

批量任务默认两小时，先依据单例实测调整时限和规模。一次顺序处理一个请求，模型在一个配置内复用。仅在确认原任务已结束后重提同一输出目录。

失败运行保留形状，重试时可恢复。若任务被强制杀死或节点失联，可能留下 `.running.lock`；先用 `squeue` 确认任务不再运行，再只删除该运行目录中的锁文件，然后执行 `--resume`。不要一次性删除所有锁，不要让两个作业写同一实验目录。

完成交互工作时，停止服务并 `exit` 退出计算节点；仅关闭 VS Code 不代表 GPU 已释放。正式批量作业通过 Slurm 管理，不依赖笔记本 SSH 会话。

