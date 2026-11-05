# HKUST HPC4：把笔记本项目放到 L20 上运行

核对日期：2026-11-01。适用于 Python / PyTorch 训练和推理。默认你已经能连接学校服务器，本指南从上传代码开始。

示例沿用你的 SSH 别名 `hkust-hpc4`、计费组 `mscaiehpc42026`，采用一个新项目名 `my-ai-project`。计费组来自你之前的开通邮件；其他项目能否使用该教学额度，应符合课程和项目组的授权范围。

## 1. 先理解整个流程

笔记本编写代码 → 上传到服务器共享目录 → CPU 节点安装依赖、准备数据 → L20 上短测 → 提交批处理训练/推理 → 看日志 → 下载结果。

| 位置 | 负责什么 |
|---|---|
| 笔记本 | 编辑、轻量测试、上传、查看和保存结果 |
| 登录节点 | 整理文件、查看软件模块、提交和管理作业 |
| CPU 计算节点 | 安装普通依赖、下载权重、预处理数据 |
| GPU 计算节点 | GPU 验证、需要 GPU 的编译步骤、训练与推理 |

学校要求计算任务通过 Slurm 调度。申请 L20 后，调度系统把你的程序安排到有可用资源的机器。通常申请一张卡即可；L20 每张有 48GB 显存。代码、环境和数据放在共享存储，换到另一台计算节点仍能访问。[学校 HPC4 说明](https://itso.hkust.edu.hk/services/academic-teaching-support/high-performance-computing/hpc4)

## 2. 本文的命令怎么执行

- **整块粘贴**：复制代码块内容到指定终端，必要时按回车。先等这一块成功，再进行下一块。
- **单独执行并等待**：如 `srun`，等分配成功、出现新的提示符后，再执行后续步骤。
- **保存成文件**：在 VS Code 中新建指定文件，将代码块保存为内容。Linux 脚本使用 UTF-8、LF 换行。
- **需要替换**：`my-ai-project` 是示例项目名；`train.py`、参数和依赖版本应按具体项目修改。

Windows PowerShell 执行标为 powershell 的代码；服务器 Bash 执行标为 bash 的代码。不要一次复制整篇文档。`#SBATCH` 行只在 `sbatch` 提交的文件中作为资源申请参数生效。

## 3. 项目放在哪里

推荐每个项目独立目录：

```text
~/projects/my-ai-project/
  train.py / infer.py       项目实际入口
  requirements.txt         Linux 可用的依赖
  configs/                 运行配置
  hpc/env.sh               每次作业恢复软件环境
  hpc/run.sbatch           通用单卡作业模板
  hpc/check_gpu.py         小规模 GPU 检查
  .venv/                   在服务器建立的 Python 环境
  data/                    小数据或指向大数据的链接
  logs/                    作业输出
  outputs/                 每次实验单独保存结果
```

个人目录适合代码、环境、小数据和重要结果；大数据与可重新下载的权重缓存可放 `/scratch/$USER/my-ai-project/`。学校列出的个人目录额度为 200GB，scratch 默认个人额度为 500GB；scratch 无备份，60 天未访问的文件会被清理。大项目也可根据组内约定使用 `/project/mscaiehpc42026/`，先确认目录权限和空间分配。[存储说明](https://itso.hkust.edu.hk/services/academic-teaching-support/high-performance-computing/hpc4/fileandstorage)

退出计算节点会释放资源。共享磁盘上的代码、虚拟环境、权重和已写入的结果会保留；进程、显存内容、当前终端激活的环境会结束。下一次运行重新加载模块、激活原来的环境即可。

## 4. 首次上传代码

**服务器登录节点，整块粘贴：**

```bash
mkdir -p ~/projects/my-ai-project
```

**笔记本 PowerShell，修改本地路径后整块粘贴：**

```powershell
Set-Location 'D:\你的项目目录'
tar --exclude=.venv --exclude=venv --exclude=.git --exclude=__pycache__ --exclude=data --exclude=outputs --exclude=logs --exclude=code-upload.tar.gz -czf code-upload.tar.gz .
scp .\code-upload.tar.gz hkust-hpc4:~/projects/my-ai-project/
```

该压缩包只传代码和配置。Windows 的虚拟环境包含平台相关文件，服务器需要重新安装 Linux 依赖。大数据单独传，避免每次更新代码都重传。

**服务器登录节点，整块粘贴：**

```bash
cd ~/projects/my-ai-project
tar -xzf code-upload.tar.gz
mkdir -p hpc logs outputs data
ls
```

首次解压使用新目录；后续解压会覆盖同名源码。运行中的实验使用独立的代码副本或固定 Git 提交，等作业结束后再更新它的工作目录。

**上传数据的示例，笔记本 PowerShell：**

```powershell
scp -r '.\data\small-dataset' hkust-hpc4:~/projects/my-ai-project/data/
```

大数据先在服务器创建目标目录，再传到已确认的 scratch 路径；把项目配置中的数据路径改成服务器 Linux 路径。代码中优先使用相对路径或命令行参数，检查并替换 `D:\...` 等本地绝对路径。

## 5. CPU 上准备环境

**登录节点，单独执行并等待：**

```bash
srun --account=mscaiehpc42026 --partition=amd --nodes=1 --ntasks=1 --cpus-per-task=4 --mem=16G --time=01:00:00 --pty bash
```

分配成功后执行 `hostname` 和 `echo "$SLURM_JOB_ID"`，确认当前计算作业。CPU 准备任务也占用相应的 CPU 额度；它能减少 GPU 在下载和安装期间的占用。

**CPU 节点，整块粘贴：**

```bash
cd ~/projects/my-ai-project
source /opt/shared/.spack-edge/dist/bin/setup-env.sh
module spider python
```

第一次激活按提示确认。查找适合项目要求的 Python 版本，再执行例如 `module load python/3.12.9`；这个名称来自学校文档示例，使用前以当前 `module spider` 输出和项目兼容要求为准。需要 Python 3.10 的项目应选对应版本。

`module load` 选择学校预装的软件，并设置当前 shell 的程序搜索路径。安装环境时用什么版本，之后运行也加载同一版本。学校新文档建议使用 Edge 软件实例、模块名称省略哈希后缀，并在作业内显式初始化，避免写入 `.bashrc`。[模块与 Slurm 环境说明](https://hkust-hpc-docs.readthedocs.io/latest/software/software-support-overview.html)

**选好 Python 后，在 CPU 节点整块粘贴：**

```bash
python --version
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
python -m pip freeze > requirements.resolved.txt
```

这部分执行一次；后续只有依赖变更才重新安装。若项目自带 Conda 环境文件或官方安装脚本，就按项目说明替换这段安装步骤，每个项目保持独立环境。

PyTorch 的 GPU 包版本按项目官方说明选择，并确认 requirements 中的安装结果。普通预编译包通常可在 CPU 节点安装；编译自定义 CUDA 扩展可能需要 CUDA Toolkit、兼容编译器，或 GPU 探测。此时查 `module spider cuda` / `module spider gcc`，根据项目版本要求加载；只有实际需要 GPU 的阶段才短时申请 L20。`nvidia-smi` 显示驱动信息，`nvcc --version` 显示编译工具版本，`torch.version.cuda` 显示 PyTorch 构建使用的 CUDA 版本，排错时分别检查。

### 保存每次运行需要的环境设置

**保存为项目内 `hpc/env.sh`。先把 Python 模块名称改为你实际使用的版本：**

```bash
# 通过 source hpc/env.sh 调用；路径以项目根目录为起点。
source /opt/shared/.spack-edge/dist/bin/setup-env.sh -y || return 1
module load python/3.12.9 || return 1
# 若项目编译/运行确实需要其他模块，在这里补充已经核实的 module load 行。
source .venv/bin/activate || return 1
export HF_HOME="/scratch/$USER/my-ai-project/cache/huggingface"
export PIP_CACHE_DIR="/scratch/$USER/my-ai-project/cache/pip"
export PYTHONUNBUFFERED=1
mkdir -p "$HF_HOME" "$PIP_CACHE_DIR" || return 1
```

**CPU 节点，整块粘贴：**

```bash
source hpc/env.sh
which python
python --version
module list
```

在此环境中按具体项目提供的命令预先下载数据和权重；需要授权的模型先完成授权与登录。若计算节点访问下载源失败，按学校网络规则选择允许的下载位置，或在笔记本下载后上传。全部准备好后，单独执行 `exit` 返回登录节点。

## 6. L20 上先做短测

**登录节点，单独执行并等待：**

```bash
srun --account=mscaiehpc42026 --partition=gpu-l20 --nodes=1 --ntasks=1 --cpus-per-task=4 --gpus-per-node=1 --mem=32G --time=00:15:00 --pty bash
```

**保存为 `hpc/check_gpu.py`：**

```python
import torch

print('PyTorch:', torch.__version__)
print('PyTorch CUDA:', torch.version.cuda)
assert torch.cuda.is_available(), '当前环境无法使用 CUDA，请检查作业分配和 PyTorch 安装'
print('GPU:', torch.cuda.get_device_name(0))
# 实际做一次 GPU 运算，确认张量和算子可用。
x = torch.randn(512, 512, device='cuda')
y = x @ x
torch.cuda.synchronize()
print('GPU 运算完成:', y.shape)
```

**分配到的 GPU 节点，整块粘贴：**

```bash
cd ~/projects/my-ai-project
source hpc/env.sh
nvidia-smi
python hpc/check_gpu.py
```

接着用你项目的一张图片、一个 batch 或几步训练测试完整流程，确认数据路径、显存、输出位置和模型依赖。上面的矩阵运算只检查基础 GPU 环境。短测结束执行 `exit`，回到登录节点用 `squeue -u "$USER"` 确认交互作业已结束。

## 7. 正式实验用批处理脚本

**保存为 `hpc/run.sbatch`，无需手动申请交互 GPU：**

```bash
#!/bin/bash
#SBATCH --job-name=ai-run
#SBATCH --account=mscaiehpc42026
#SBATCH --partition=gpu-l20
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gpus-per-node=1
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err

# 任一步失败就停止，避免继续运行依赖于失败步骤的命令。
set -e
cd "$SLURM_SUBMIT_DIR"
source hpc/env.sh
export OMP_NUM_THREADS="$SLURM_CPUS_PER_TASK"
echo "作业编号: $SLURM_JOB_ID"
hostname
date
nvidia-smi
python hpc/check_gpu.py
# 提交时传入项目的 Python 入口与参数。
if [ "$#" -eq 0 ]; then
    echo '请在 sbatch hpc/run.sbatch 后填写 Python 文件与参数'
    exit 2
fi
srun python -u "$@"
date
```

资源参数是单卡起步模板，按项目实际需求和当前分区限制调整。`--mem=32G` 是系统内存；显存由所申请的 L20 提供。单卡代码先使用 `cuda` 或 `cuda:0`，让 Slurm 管理可见 GPU。

**登录节点，整块粘贴：**

```bash
cd ~/projects/my-ai-project
mkdir -p logs outputs
bash -n hpc/env.sh
bash -n hpc/run.sbatch
```

`bash -n` 检查脚本语法；无输出且正常结束即可。日志目录必须在提交前存在。

**训练提交示例：替换入口与参数后单独执行。**

```bash
sbatch hpc/run.sbatch train.py --config configs/train.yaml
```

**推理提交示例：按项目实际参数修改。**

```bash
sbatch hpc/run.sbatch infer.py --input data/example.jpg --output outputs/infer01
```

如果项目使用 `python -m 包名`，可以写 `sbatch hpc/run.sbatch -m 包名 ...`。若入口是其他 CLI、torchrun 或 shell 脚本，应修改模板最后的执行命令。

提交返回 `Submitted batch job 123456`，记下这个编号。Slurm 随后排队、分配 GPU、执行脚本、保存日志并释放资源。提交成功后可以断开连接、关闭笔记本，批处理作业继续由调度系统管理。交互式 `srun --pty bash` 适合短测；长训练使用这里的 `sbatch`。[Slurm 提交和参数说明](https://itso.hkust.edu.hk/services/academic-teaching-support/high-performance-computing/hpc4/slurm)

## 8. 查看状态、日志与停止任务

**登录节点，按需要单独执行；把 123456 改成实际作业编号：**

```bash
squeue -u "$USER"
scontrol show job 123456
tail -n 80 logs/ai-run-123456.out
tail -n 80 logs/ai-run-123456.err
tail -f logs/ai-run-123456.out
```

`PD` 表示等待分配，`R` 表示运行。看排队原因区分资源繁忙和账户/配额限制。`tail -f` 持续显示日志，用 Ctrl+C 结束查看，作业继续运行。待作业启动后才会生成日志文件。

```bash
sacct -j 123456 --format=JobID,State,Elapsed,ExitCode,MaxRSS
```

该命令用于查询历史状态（依赖站点记账服务）。作业从 squeue 消失后，用它和日志确认是成功、失败还是超时。

```bash
scancel 123456
```

只在确定要停止该作业时执行 scancel。它会终止程序，所以训练程序应定期把 checkpoint 写入共享存储。

| 现象 | 优先检查 |
|---|---|
| 长期 PD | `scontrol show job` 的 Reason、申请资源和时限 |
| CUDA 不可用 | 是否分配了 GPU、加载的环境、PyTorch 是否为 GPU 构建 |
| CUDA out of memory | 减小 batch/分辨率，按项目支持启用混合精度等措施 |
| OUT_OF_MEMORY | 作业系统内存需求与 `--mem`，区别于 GPU 显存不足 |
| TIMEOUT | 从 checkpoint 恢复，并在分区允许范围内申请更长时间 |
| 找不到包或模块 | 作业内是否 source env.sh，模块与安装时是否一致 |
| 找不到数据 | 工作目录、Linux 路径、文件是否上传完整 |
| 日志没有及时刷新 | 使用 `python -u`，检查程序是否卡在下载或数据读取 |
| bad interpreter / 换行错误 | 将脚本保存为 LF，检查首行 `#!/bin/bash` |

## 9. 保存结果与恢复训练

每次实验使用不同输出目录，例如 `outputs/exp01/`，一起保留参数、随机种子、代码版本、依赖版本和日志。训练 checkpoint 通常需要模型参数、优化器状态、训练步数及相关随机状态；恢复方式由项目代码实现，重新申请 GPU 后按项目的 resume 参数继续。

**笔记本 PowerShell，修改本地路径后整块粘贴：**

```powershell
New-Item -ItemType Directory -Force 'D:\实验结果\my-ai-project'
scp -r hkust-hpc4:~/projects/my-ai-project/outputs 'D:\实验结果\my-ai-project\'
scp -r hkust-hpc4:~/projects/my-ai-project/logs 'D:\实验结果\my-ai-project\'
```

重要结果及时下载。只存在显存或进程内的数据会在作业结束时消失；写入 scratch 的结果还需遵守其清理周期。

## 10. 控制资源占用，以及换项目时改什么

先上传、安装、下载和准备输入，再申请 GPU。GPU 分配处于运行状态时，即使等待输入或下载，也占用已分配资源；排队期间尚未获得 GPU。完成交互调试后及时退出并查看队列。具体收费和余额以学校账户报告及当期规则为准。

换一个项目时，通常只需修改项目目录、Python/依赖环境、数据与权重路径、运行命令和资源需求。保留相同的工作方式：**CPU 准备 → 单卡短测 → sbatch 正式运行 → 下载结果**。申请多张卡前，先确认程序已实现多 GPU 并行；申请数量本身不会把单卡程序自动拆分。

快速回顾：第一次配置完成后，日常只需上传更新的代码/配置，在登录节点进入项目目录，提交 `sbatch hpc/run.sbatch ...`，记录编号、查看日志、取回结果。环境变更时先在短测中验证，避免一开始就提交长时间作业。

本指南提供操作模板和站点规则核对结果，尚未在你的 HPC 账户上执行安装或提交计算任务。不同项目的 Python、CUDA 与依赖版本需要按其官方要求选定。
