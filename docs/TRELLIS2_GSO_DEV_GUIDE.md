# TRELLIS.2：共享数据集上的 10 对象 × 2 种子实验

服务器代码仓库位于 `~/project/cv-final-project/`。本指南替代之前按实验复制 data 的方案。运行代码、依赖和权重仍使用已固定的 TRELLIS.2 版本。新的服务器 GPU 作业尚未在你的账户执行。

## 1. 目录职责

```text
cv-final-project/
  src/asset3d/                  共用 pipeline、评价、记录代码
    backends/hunyuan2.py         混元接口
    backends/trellis2.py         TRELLIS.2 接口
  configs/                      两种模型分别配置
  scripts/  slurm/              安装、启动和调度入口
  datasets/gso-v1/data/          共享的 GSO 图片和参考模型，仅存一份
    manifests/gso-dev-v1.csv     对象 ID → 图片、参考模型、数据划分
    rendered/gso-formal-v1/      所有已准备的对象文件
  models/                       权重和下载缓存，不提交 Git
    huggingface/
    dinov3-vitl16-pretrain-lvd1689m/
  experiments/
    trellis2-gso-dev-v1/
      batch.yaml                人工设置的批次配置，提交 Git
      selection.csv             自动生成，引用共享数据的相对路径
      resolved.json             数据哈希与展开后的配置快照
      resolved-configs/         实际交给生成程序的固定配置
      logs/                     本批次 Slurm 日志
      results/                  GLB、运行记录、viewer 预设
    下一次实验/                 与其他批次平级
  gso-viewer/                   独立浏览器
```

旧 `asset3d-gso-v1-20261108/` 是历史归档，保留其配置和运行结果以便追溯。新实验使用 `experiments/<批次>/`，批次之间平级。当前不会自动删除或移动旧包。已有的 `src/` 就是 pipeline 代码目录，无需再把源码复制到每个实验里。

生成程序仍保存每次运行的 `input.png` 和 `foreground.png`，用于检查实际送入模型的图片；参考模型和整个数据集通过路径共享。Git 保存代码、小配置、数据来源及哈希，数据、权重和生成结果保存在本地或服务器。

## 2. 首次获取代码

服务器登录节点：

```bash
mkdir -p ~/project
cd ~/project
git clone --branch trellis2-gso-dev --single-branch https://github.com/Zr21340398/cv-final-project.git
cd ~/project/cv-final-project
```

已经克隆过时只需进入仓库并执行 `git pull`。后续命令都从仓库根目录执行。

## 3. 共享数据只准备一次

本次使用与混元相同的 10 个开发对象及原始视角。已有的 69 MiB 数据压缩包仍可使用，不需要重新制作。服务器先创建共享目录：

```bash
cd ~/project/cv-final-project
mkdir -p datasets/gso-v1
```

若压缩包还在笔记本，PowerShell 上传：

```powershell
scp 'D:\AIEproject\MAIE5421_CV\Final Project\dist\trellis2-gso-dev-data.tar.gz' hkust-hpc4:~/project/cv-final-project/datasets/gso-v1/
```

如需重新制作本地包，仍可使用 `scripts/package_trellis2_gso_dev.py`，输入旧实验的原始数据清单。若压缩包已在服务器主目录，服务器执行：

```bash
cp -n ~/trellis2-gso-dev-data.tar.gz datasets/gso-v1/
```

如果之前放在其他位置，将上面源路径替换成实际位置。确认 `datasets/gso-v1/data` 尚未准备后解压一次：

```bash
tar -xzf datasets/gso-v1/trellis2-gso-dev-data.tar.gz -C datasets/gso-v1
```

下一批实验直接引用这份数据，不再上传或解压。共享清单支持 10 行或完整 30 行，新入口只检查 `batch.yaml` 选中的对象。以后新增对象时补充共享清单和对应文件即可。版本不同的渲染图片应使用新数据版本目录，保留既有版本。

已经渲染的这套输入含固定视角和归一化参考网格，使用上述已核验的数据包最便于复现。原始 GSO 下载链接及许可保存在 `data/manifests/gso-selection.csv`；重新从原始数据生成图片还需要复现渲染步骤。项目暂未提供一键下载同一套已渲染数据的公开地址。

## 4. 模型权重与独立环境

权重也只准备一次，不跟随批次复制。在每次准备和提交终端中设置相同位置：

```bash
cd ~/project/cv-final-project
export HF_HOME="$PWD/models/huggingface"
export ASSET3D_DINOV3_DIR="$PWD/models/dinov3-vitl16-pretrain-lvd1689m"
mkdir -p "$HF_HOME"
```

若学校推荐使用 scratch，可将上述两项设置为自己的 scratch 位置；保持下载和作业中的设置一致。`models/` 被 Git 忽略。独立环境使用 `.venv-trellis2`，混元仍使用 `.venv-hpc`。

首次安装参考 [PILOT_GUIDE.md](PILOT_GUIDE.md) 第 5～7、10 节：申请 GPU，加载 CUDA 12.4 与 Python 3.10/3.11，运行 `bash scripts/install_trellis2_hpc.sh`。DINOv3 按该指南下载到上面的 `ASSET3D_DINOV3_DIR`，代码会核验权重哈希；不要将第三方指南中示例账户目录直接照抄。

环境准备后，在允许下载的计算节点中：

```bash
source .venv-trellis2/bin/activate
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE
asset3d download --config configs/trellis2_gso_dev.yaml
```

此命令下载固定版本的主模型与辅助权重，并使用已准备好的本地 DINOv3 文件。

## 5. 配置并核验批次

`experiments/trellis2-gso-dev-v1/batch.yaml` 指定：

- 共享数据清单的位置（相对于仓库根目录）。
- 10 个对象 ID、dev 划分、42 和 123 两个种子。
- TRELLIS.2 专用模型配置，以及核对图片/参考模型的冻结哈希表。

在任意已安装本项目的 Python 环境中运行下面命令，只检查文件，不启动 GPU：

```bash
python scripts/run_batch.py experiments/trellis2-gso-dev-v1/batch.yaml --prepare-only
```

程序生成 `selection.csv`、`resolved.json` 和 `resolved-configs/`。共享清单中未被选中的对象可以暂未下载。已冻结的批次改变数据或配置时会拒绝继续；要调整参数，请新建批次目录并复制小文件 `batch.yaml`，然后编辑对象、模型配置或种子。

## 6. 提交作业

先在 GPU 分配中用 `asset3d doctor --gpu --backend trellis2` 检查环境；首次安装后建议先执行单个 `asset3d generate`，输入使用 `datasets/gso-v1/data/rendered/gso-formal-v1/gso_01/view-000.png`，配置 `configs/trellis2_gso_dev.yaml`，输出指定为独立目录 `experiments/trellis2-smoke/results`。

整批在登录节点提交：

```bash
cd ~/project/cv-final-project
export HF_HOME="$PWD/models/huggingface"
export ASSET3D_DINOV3_DIR="$PWD/models/dinov3-vitl16-pretrain-lvd1689m"
mkdir -p logs experiments/trellis2-gso-dev-v1/logs
sbatch --output=experiments/trellis2-gso-dev-v1/logs/%x-%j.out slurm/trellis2_gso_dev.sbatch experiments/trellis2-gso-dev-v1/batch.yaml
squeue -u "$USER"
```

脚本仅启动 TRELLIS.2 环境，检查批次后串行运行 20 次。生成结果在 `experiments/trellis2-gso-dev-v1/results/trellis2_gso_dev/<对象>/seed-<种子>/`。结果根目录有 `experiment.json`、`failures.json` 和 `viewer-manifest.json`。同一源码、配置和数据下，重新提交相同命令可续跑；失败项查看各次 `manifest.json`、`run.log` 和作业日志。

当前基线采用官方默认采样设置、1024 cascade、2048 贴图、100 万面导出目标。混元之前使用 4 万面导出，图片预处理也不同，报告中要说明比较条件。

## 7. 下载与 viewer

把 `experiments/trellis2-gso-dev-v1/` 下载到笔记本仓库的同名位置。笔记本共享数据也放到 `datasets/gso-v1/`，通过已有数据包一次性准备即可。预设使用相对路径；保留这种布局时图片和参考模型可以直接解析。

启动 `gso-viewer/start.bat` 并刷新实验列表。viewer 已支持新结构，同时兼容旧实验包。如果参考路径变化，可重新建立预设：

```powershell
.\.venv\Scripts\asset3d.exe viewer-index --experiment experiments/trellis2-gso-dev-v1/results --output experiments/trellis2-gso-dev-v1/results/viewer-manifest.json --reference-dir datasets/gso-v1/data/rendered/gso-formal-v1 --overwrite
```

不要在下载到另一台机器的历史结果上直接续跑；冻结运行计划记录了原运行位置及源码信息。新机器的新运行使用新批次。
