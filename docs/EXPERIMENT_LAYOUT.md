# 目录和历史实验迁移

服务器仓库为 `~/project/cv-final-project/`。不同批次都直接放在 experiments 下，不互相嵌套。数据下载和权重路径统一见 [DATA_AND_MODELS.md](DATA_AND_MODELS.md)。

## 本次迁移

- 旧包 `asset3d-gso-v1-20261108/data/` 移至 `datasets/gso-v1/data/`，保留完整 30 对象数据和来源信息。
- 旧包 `results/gso-dev-v1/` 移至 `experiments/asset3d-gso-v1-20261108/results/`。
- 旧日志移至该实验 `logs/`。配置从原冻结计划提取到该实验 `configs/`。
- 旧源码保存在本批次 `legacy-source/`，作为只读历史快照；当前生成统一使用根目录 `src/asset3d/`。历史小清单另存于 `provenance/`，共享大数据不重复复制。
- 原计划和运行记录保持字节内容不变；viewer 预设重建，指向共享参考模型。

## 执行历史批次核验

```bash
python scripts/run_batch.py experiments/asset3d-gso-v1-20261108/batch.yaml
```

历史批次已完成；此命令在 CPU 上校验 60 次运行的所有记录产物并重建预设。GLB 不在 Git 中，只有源码的新服务器可跳过这一步，或先把已有结果目录复制到目标 results。它不对历史结果启动 GPU 重新生成。

## 再生成同样的混元配置

```bash
source .venv-hpc/bin/activate
python scripts/run_batch.py experiments/hunyuan2-gso-dev-rerun/batch.yaml --prepare-only
```

在 GPU 分配内去掉 `--prepare-only` 执行新一轮生成。输入为相同 10 个对象，配置为原始 50/30/20 步 × 2 种子，使用当前共用 runner，结果写入新批次 results。旧实验采用独立进程调度，当前 runner 采用串行复用模型，因此重跑成本需要重新计量。禁止修改历史记录中的源码哈希来冒充续跑。

## 其他机器如何同步

Git pull 只同步配置、代码和说明，不会自动移动服务器的大文件。若该机器还有完整旧包，先停止正在使用它的作业，确认共享目标和新 results 目标为空，再分别移动 data 和 results/gso-dev-v1 到上述新位置。已有共享数据时先核对哈希，避免覆盖；历史 results 可以从本机复制过去。完成后执行历史批次核验命令。批次配置无需复制整套代码。

本地 viewer 默认扫描 `experiments/<批次>/results/viewer-manifest.json`。所有相对路径都在仓库内，整批下载结果、共享数据保持同一相对布局即可查看。


混元重跑的 Slurm 入口（先完成统一准备指南中的混元环境与权重下载）：

```bash
cd ~/project/cv-final-project
export HF_HOME="$PWD/models/huggingface"
export U2NET_HOME="$PWD/models/rembg"
mkdir -p logs experiments/hunyuan2-gso-dev-rerun/logs
sbatch --output=experiments/hunyuan2-gso-dev-rerun/logs/%x-%j.out slurm/hunyuan2_gso_dev.sbatch experiments/hunyuan2-gso-dev-rerun/batch.yaml
```
