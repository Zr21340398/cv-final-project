# 单图 3D 资产生成与实验工作台

项目用混元 3D 2.0 和 TRELLIS.2 的固定版本权重，把图片生成带材质的 GLB，并记录输入、配置、随机种子、耗时和文件哈希。两种模型各自使用独立后端和 Python 环境。

## 从哪里开始

1. [代码、数据、模型权重准备](docs/DATA_AND_MODELS.md)：Git 获取代码，共享数据传输一次，权重独立下载。
2. [服务器环境安装](docs/HPC4_SETUP.md)。
3. [TRELLIS.2 的 10 对象 × 2 种子实验](docs/TRELLIS2_GSO_DEV_GUIDE.md)。
4. [目录与历史混元实验](docs/EXPERIMENT_LAYOUT.md)。
5. [viewer 使用与预设格式](gso-viewer/README.md)。

## 目录

```text
src/asset3d/              共用 pipeline、评价和记录；backends 区分两种模型
configs/                 模型配置
scripts/  slurm/          操作与调度入口
datasets/gso-v1/data/     共享 GSO 原始文件、输入图片、参考网格及清单
models/                  权重缓存
experiments/             每个批次只包含配置、记录和输出
gso-viewer/              独立 3D 工作台
```

数据、权重和生成结果不进入 Git。每个实验通过 batch.yaml 选择数据 ID、模型配置和种子，参考网格只保存一份。生成过程保留每次实际输入和预处理图以便排查。

## 已有结果

混元开发集 60 次生成已完成，迁移后位于 `experiments/asset3d-gso-v1-20261108/results/`。历史报告见 [gso-dev-v1](docs/results/gso-dev-v1/README.md)，五图预实验见 [pilot03](docs/results/pilot03/README.md)。原运行记录保留用于追溯，新运行单独建批次。TRELLIS.2 本轮代码已准备，服务器实测结果待运行。

```bash
python scripts/run_batch.py experiments/trellis2-gso-dev-v1/batch.yaml --prepare-only
```

上面命令只核验共享数据并冻结批次配置。详细生成、续跑、下载与展示操作请按指南执行。
