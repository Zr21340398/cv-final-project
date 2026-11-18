# TRELLIS.2 GSO 开发集实验

本批次为 10 个开发对象 × 种子 42、123，共 20 次生成。默认 1024 cascade、2048 贴图、100 万面简化目标；采样参数来自固定版本官方配置。两模型原生预处理与面数设置不同，报告中分别记录。

## 1. 准备代码、数据和权重

统一按 [SERVER_SETUP.md](SERVER_SETUP.md) 操作，使用 Git 克隆代码、一次性传输共享数据目录、独立下载模型权重。无需制作或上传压缩包。环境安装也在该指南中。服务器根目录为 `~/project/cv-final-project/`。

批次配置 `experiments/trellis2-gso-dev-v1/batch.yaml` 选择数据清单、10 个 ID、模型配置和两个种子。生成的配置快照和结果位于该批次目录。

## 2. 先检查数据

```bash
cd ~/project/cv-final-project
source .venv-trellis2/bin/activate
python scripts/run_batch.py experiments/trellis2-gso-dev-v1/batch.yaml --prepare-only
```

核验原图与参考模型哈希，只使用选中的对象。相同批次的数据或配置变化时会拒绝继续；调整参数应创建新的 batch.yaml 所在目录。

## 3. 提交单例与整批作业

安装作业完成后，先在登录节点提交单例：

```bash
cd ~/project/cv-final-project
export HF_HOME="$PWD/models/huggingface"
export ASSET3D_DINOV3_DIR="$PWD/models/dinov3-vitl16-pretrain-lvd1689m"
mkdir -p logs experiments/trellis2-gso-smoke/logs
sbatch --time=01:00:00 --output=experiments/trellis2-gso-smoke/logs/%x-%j.out slurm/trellis2_gso_dev.sbatch experiments/trellis2-gso-smoke/batch.yaml
```

该批次只生成 `gso_01`、种子 42，结果在 `experiments/trellis2-gso-smoke/results/`。检查作业完成、该目录内 `manifest.json` 显示 completed 且 GLB 可打开之后，再提交完整批次：

```bash
mkdir -p experiments/trellis2-gso-dev-v1/logs
sbatch --output=experiments/trellis2-gso-dev-v1/logs/%x-%j.out slurm/trellis2_gso_dev.sbatch experiments/trellis2-gso-dev-v1/batch.yaml
squeue -u "$USER"
```

完整批次包含 20 次生成，输出在 `experiments/trellis2-gso-dev-v1/results/`。每次生成目录含 GLB、实际输入图片及 manifest；结果根目录有冻结计划、失败清单和 viewer 预设。同一源码、参数和数据下可重复相同命令续跑。作业自动加载 `local/hpc4_modules.sh`，无需等待 GPU 后手动执行命令。单例和完整批次各自独立，首个对象会生成两次。

## 4. 下载和展示

只下载 `experiments/trellis2-gso-dev-v1/` 到笔记本同名位置，共享数据已存在时无需重复下载。保留仓库内相对布局，viewer 刷新即可发现该实验。参考模型路径变动时：

```powershell
.\.venv\Scripts\asset3d.exe viewer-index --experiment experiments/trellis2-gso-dev-v1/results --output experiments/trellis2-gso-dev-v1/results/viewer-manifest.json --reference-dir datasets/gso-v1/data/rendered/gso-formal-v1 --overwrite
```

历史混元批次见 [EXPERIMENT_HISTORY.md](EXPERIMENT_HISTORY.md)。新服务器上只有 Git 代码时，历史生成结果需要另外下载，新的 TRELLIS 批次可以直接从共享数据生成。

## 5. 临时用原始正面照片重跑冰箱和音箱

本次只检查输入图片的影响。两个对象均读取共享数据中的 `raw/gso/<对象>/thumbnails/2.jpg`。冰箱为 gso_01，绿色音箱为 gso_02；这两张图片都是正面图。脚本读取原实验冻结的生成参数，种子仍为 42、123，共生成四个模型。

处理过程为：原始 JPG → 官方 RMBG-2.0 抠图 → 现有居中缩放处理 → TRELLIS.2 生成 → 白模和带材质 GLB 导出。本次保留照片细节，未添加降噪。通用 pipeline 与批次配置保持原状。

将 `scripts/rerun_trellis2_front.py` 和 `slurm/trellis2_front_rerun.sbatch` 上传到服务器项目中的同名位置。服务器需已有完整安装的 TRELLIS.2 环境、模型权重、两张 JPG 和原批次 results。等待原完整批次作业结束后，在服务器项目根目录提交：

```bash
cd ~/projects/cv-final-project
mkdir -p logs
sbatch slurm/trellis2_front_rerun.sbatch
```

这里使用服务器实际的 `~/projects/` 路径。作业申请一张 L20，时间上限两小时，可通过 `sbatch --time=04:00:00 slurm/trellis2_front_rerun.sbatch` 调整。日志为 `logs/trellis2-front-作业号.out`。GPU 分配后自动运行。

每个对象的两个种子都成功导出后，脚本才替换 `experiments/trellis2-gso-dev-v1/results/trellis2_gso_dev/gso_01/` 或 `gso_02/`。旧模型会被覆盖，其余八个对象保持原结果；无需新建批次。失败的对象保留旧结果，并在 results 下留下 `.front-gso_XX-*` 临时诊断目录。已经成功替换的对象保留新结果。

每个 seed 目录保存 `source.jpg`（原始文件）、`input.png`（原图的 PNG 版本）、`masked.png`（抠图结果）、`foreground.png`（现有流程居中缩放后的前景）、`shape_raw.glb`、`asset.glb` 和 `manifest.json`。官方模型还会对前景进行内部裁剪与背景合成。manifest 的 `input_override` 记录此次来源变更，图片摘要指向 masked.png。

viewer 预设自动刷新。下载更新后的两个对象目录和 `results/viewer-manifest.json` 到本机同名位置，刷新 viewer，即可在原实验下看新模型和原始输入图。重点查看冰箱顶部、音箱整体外形，以及 foreground.png 的边缘是否完整。

此次是同批次中的局部输入替换。原 `experiment.json` 与批次配置仍记录最初的渲染图方案，后续统一整理 pipeline 时再处理。请使用本节专用脚本重新尝试；原完整批次续跑入口会核对旧输入摘要，遇到这两个替换结果时会报输入不一致。
