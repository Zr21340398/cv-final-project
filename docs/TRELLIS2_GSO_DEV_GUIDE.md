# TRELLIS.2：GSO 开发集 20 次生成操作指南

本分支运行 10 个已选开发对象，每个对象使用 42 和 123 两个种子，共 20 次。它是使用已有权重的推理实验；混元的实验结果与环境保存在各自目录。完成后可以对照两个模型生成的形状和外观。请先做单对象检查，再提交整批。本指南中的服务器操作尚未在你的账户执行。

## 1. 实验内容与比较条件

- 模型：`configs/trellis2_gso_dev.yaml` 继承已完成预实验的 `configs/trellis2.yaml`，1024 cascade，低显存模式，导出 PBR GLB，贴图 2048，简化目标 100 万面。
- 原始数据：与混元开发实验相同的 10 张 GSO 输入图和 10 个参考模型；提交前检查它们的 SHA-256。两模型各自使用不同的原生图片预处理和三维表示，比较结果要在报告中说明这一点。相同种子只是方便组织重复实验，两个模型的随机过程不同。
- `shape_raw.glb` 是 TRELLIS.2 导出前几何，`asset.glb` 是烘焙并简化后的带材质模型。它和混元的 4 万面导出设置不同，比较时分别记录。
- 结果单独写入 `results/trellis2-gso-dev-v1`，保留原来的混元目录。自动生成 viewer 预设及每次运行记录。

## 2. 上传代码和数据

在笔记本项目根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts/package_project.py
```

将 `dist/asset3d-source.tar.gz` 上传至服务器，再解压到你的项目目录。若目录已有文件，先核对并备份；解压会覆盖包内同名源码。安装环境、第三方仓库、模型缓存和实验结果都不在源码包中。

还需上传现有 `asset3d-gso-v1-20261108/data/`，保持 `manifests/gso-formal-v1.csv` 与 `rendered/gso-formal-v1/` 的相对位置。此 CSV 包含 30 行，当前读取器会核验所有行对应的文件，因此应上传完整 data 目录；生成时只选 `dev` 的 10 行。已有文件可复用，先用下面检查确认内容。

服务器进入项目根目录，假设数据放在 `~/asset3d-gso-v1-20261108/data`：

```bash
cd ~/asset3d-formal
export GSO_MANIFEST="$HOME/asset3d-gso-v1-20261108/data/manifests/gso-formal-v1.csv"
mkdir -p logs results
```

如果实际路径不同，修改 `GSO_MANIFEST`。不要照抄其他账户的 `/home/` 路径。

## 3. TRELLIS.2 独立环境和模型

若你的账户已有可用的 `.venv-trellis2`，先复用并在 GPU 节点运行 `asset3d doctor --gpu --backend trellis2`。否则参考 [预实验指南](PILOT_GUIDE.md) 第 5～7、10 节准备 CUDA 12.4、Python 3.10/3.11、独立环境、模型访问权限与缓存。`scripts/install_trellis2_hpc.sh` 在申请到的 GPU 节点运行，会安装并编译扩展。

本代码还需要 DINOv3 本地文件：按预实验指南第 5 节准备模型文件，设置 `ASSET3D_DINOV3_DIR`；权重会按代码中的 SHA-256 校验。主模型和其他辅助模型按指南下载，并确保下载和作业使用同一 `HF_HOME`。可在提交终端设置：

```bash
export HF_HOME="/scratch/$USER/project3/cache/huggingface"
export ASSET3D_DINOV3_DIR="$HOME/models/dinov3-vitl16-pretrain-lvd1689m"
source .venv-trellis2/bin/activate
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE
asset3d download --config configs/trellis2_gso_dev.yaml
python scripts/check_trellis2_gso_dev.py "$GSO_MANIFEST"
```

下载前确认 DINOv3 已准备好。检查会读取全清单、校验 10 个开发样本的原图、参考模型和透明背景。出现缺文件或哈希不同，先核对上传目录。

## 4. 先生成一个样例

在登录节点申请 GPU；模块加载按你账户的实际配置执行，保持上一步缓存变量：

```bash
srun --account=mscaiehpc42026 --partition=gpu-l20 --nodes=1 --ntasks=1 --gpus-per-node=1 --time=01:00:00 --pty bash
```

计算节点中：

```bash
cd ~/asset3d-formal
source .venv-trellis2/bin/activate
export HF_HOME="/scratch/$USER/project3/cache/huggingface"
export ASSET3D_DINOV3_DIR="$HOME/models/dinov3-vitl16-pretrain-lvd1689m"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
asset3d doctor --gpu --backend trellis2
asset3d generate --image "$HOME/asset3d-gso-v1-20261108/data/rendered/gso-formal-v1/gso_01/view-000.png" \
  --config configs/trellis2_gso_dev.yaml --seed 42 --output results/trellis2-smoke-gso01
exit
```

实际数据路径不同时调整 `--image`。该样例目录与整批独立，所以整批会重新生成一次 gso_01/42。检查 `manifest.json` 的状态为 completed、`asset.glb` 可打开后继续。遇到 GPU 内存或依赖错误时保留 `run.log` 和 manifest 排查。

## 5. 提交 20 次生成

在登录节点项目根目录，重新确认两个路径变量，再提交：

```bash
export GSO_MANIFEST="$HOME/asset3d-gso-v1-20261108/data/manifests/gso-formal-v1.csv"
export HF_HOME="/scratch/$USER/project3/cache/huggingface"
export ASSET3D_DINOV3_DIR="$HOME/models/dinov3-vitl16-pretrain-lvd1689m"
mkdir -p logs
sbatch slurm/trellis2_gso_dev.sbatch "$GSO_MANIFEST" results/trellis2-gso-dev-v1
squeue -u "$USER"
```

作业申请一张 L20、最多四小时；按队列与实测耗时调整。脚本选择 `.venv-trellis2`、离线模式、固定配置和种子，写入日志 `logs/trellis2-gso-dev-<作业号>.out`。`failures.json` 列出本次运行失败项；整体作业失败时查看日志和各次 `run.log`。同一目录可使用相同命令续跑，程序会核对数据、配置和源码。若计划或源码已变化，使用新结果目录。

## 6. 下载和查看

结果位于：

```text
results/trellis2-gso-dev-v1/
  experiment.json                  冻结的实验计划
  viewer-manifest.json             viewer 预设
  failures.json                   本次运行失败记录
  trellis2_gso_dev/gso_01/seed-42/
    input.png  foreground.png  shape_raw.glb  asset.glb  manifest.json
```

将整个实验目录下载到本机项目的 `results/`。预设中的参考模型路径来自服务器；复制到本机后，在已装本项目的 Python 环境中运行下面命令，指向本机参考模型目录，并重新生成预设：

```powershell
.\.venv\Scripts\asset3d.exe viewer-index --experiment results/trellis2-gso-dev-v1 --output results/trellis2-gso-dev-v1/viewer-manifest.json --reference-dir asset3d-gso-v1-20261108/data/rendered/gso-formal-v1 --overwrite
```

参考模型会按冻结哈希核验。启动 `gso-viewer/start.bat`，刷新实验列表，选择 TRELLIS 实验。混元和 TRELLIS 目前是两个实验预设；跨实验逐模型比较可在窗口里手动打开 GLB，或后续生成一个联合预设。
