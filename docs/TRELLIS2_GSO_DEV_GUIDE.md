# TRELLIS.2 GSO 开发集实验

本批次为 10 个开发对象 × 种子 42、123，共 20 次生成。默认 1024 cascade、2048 贴图、100 万面简化目标；采样参数来自固定版本官方配置。两模型原生预处理与面数设置不同，报告中分别记录。

## 1. 准备代码、数据和权重

统一按 [DATA_AND_MODELS.md](DATA_AND_MODELS.md) 操作，使用 Git 克隆代码、一次性传输共享数据目录、独立下载模型权重。无需制作或上传压缩包。环境安装见 [HPC4_SETUP.md](HPC4_SETUP.md)。服务器根目录为 `~/project/cv-final-project/`。

批次配置 `experiments/trellis2-gso-dev-v1/batch.yaml` 选择数据清单、10 个 ID、模型配置和两个种子。生成的配置快照和结果位于该批次目录。

## 2. 先检查数据

```bash
cd ~/project/cv-final-project
source .venv-trellis2/bin/activate
python scripts/run_batch.py experiments/trellis2-gso-dev-v1/batch.yaml --prepare-only
```

核验原图与参考模型哈希，只使用选中的对象。相同批次的数据或配置变化时会拒绝继续；调整参数应创建新的 batch.yaml 所在目录。

## 3. 单例检查与整批作业

首次安装后，在已申请的 GPU 节点检查：

```bash
cd ~/project/cv-final-project
source .venv-trellis2/bin/activate
export HF_HOME="$PWD/models/huggingface"
export ASSET3D_DINOV3_DIR="$PWD/models/dinov3-vitl16-pretrain-lvd1689m"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
asset3d doctor --gpu --backend trellis2
asset3d generate --image datasets/gso-v1/data/rendered/gso-formal-v1/gso_01/view-000.png --config configs/trellis2_gso_dev.yaml --seed 42 --output experiments/trellis2-smoke/results
```

单例成功后退出 GPU 分配，在登录节点提交整批：

```bash
cd ~/project/cv-final-project
export HF_HOME="$PWD/models/huggingface"
export ASSET3D_DINOV3_DIR="$PWD/models/dinov3-vitl16-pretrain-lvd1689m"
mkdir -p logs experiments/trellis2-gso-dev-v1/logs
sbatch --output=experiments/trellis2-gso-dev-v1/logs/%x-%j.out slurm/trellis2_gso_dev.sbatch experiments/trellis2-gso-dev-v1/batch.yaml
squeue -u "$USER"
```

单卡作业最多四小时，实际耗时以运行记录为准。整批输出在 `experiments/trellis2-gso-dev-v1/results/`。每次生成目录含 GLB、实际输入图片及 manifest；结果根目录有冻结计划、失败清单和 viewer 预设。同一源码、参数和数据下可重复相同命令续跑。

## 4. 下载和展示

只下载 `experiments/trellis2-gso-dev-v1/` 到笔记本同名位置，共享数据已存在时无需重复下载。保留仓库内相对布局，viewer 刷新即可发现该实验。参考模型路径变动时：

```powershell
.\.venv\Scripts\asset3d.exe viewer-index --experiment experiments/trellis2-gso-dev-v1/results --output experiments/trellis2-gso-dev-v1/results/viewer-manifest.json --reference-dir datasets/gso-v1/data/rendered/gso-formal-v1 --overwrite
```

历史混元批次见 [EXPERIMENT_LAYOUT.md](EXPERIMENT_LAYOUT.md)。新服务器上只有 Git 代码时，历史生成结果需要另外下载，新的 TRELLIS 批次可以直接从共享数据生成。
