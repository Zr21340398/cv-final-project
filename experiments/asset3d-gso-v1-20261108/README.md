# 混元 GSO 开发集历史批次

迁移前路径为 `asset3d-gso-v1-20261108/results/gso-dev-v1`。现在生成结果在本目录 `results/`，数据共享 `datasets/gso-v1/`，配置快照在 `configs/`。

原实验源码在本批次 `legacy-source/` 中只读归档；当前程序统一使用仓库根目录源码。也可以从 Git 提交 `c1c0afe` 的 `asset3d-gso-v1-20261108/src/` 取得。原始 `experiment.json`、运行 manifest、GLB 保持原样；旧的服务器绝对路径只作为历史证据保留，viewer 重新引用共享数据。

执行 `python scripts/run_batch.py experiments/asset3d-gso-v1-20261108/batch.yaml` 会在 CPU 上核验全部 60 次结果，并重建 viewer 预设。缺少本地结果时会报缺文件；Git 不包含 GLB，需要从已保存的实验结果目录复制。新一轮生成使用 `experiments/hunyuan2-gso-dev-rerun/batch.yaml`，输出到独立批次。新入口使用当前共用 pipeline，历史的独立进程调度协议保存在原计划中。
