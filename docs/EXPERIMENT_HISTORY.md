# 历史实验记录

## 2026-11-07：五图模型选型预实验

在 HKUST HPC4 的一张 L20 上，使用陶罐、杯子、茶壶、魔方和金属铃五张图片，混元和 TRELLIS.2 各使用种子 42、123，共 20 次；pilot03 全部完成。此前 pilot02 的混元上色超时、TRELLIS C++ 库导入失败，修复后执行 pilot03。

| 指标 | 混元 3D 2.0 | TRELLIS.2 |
|---|---:|---:|
| 完成数 | 10/10 | 10/10 |
| 平均完整管线耗时 | 120.63 秒 | 313.27 秒 |
| 最终 GLB 平均大小 | 3.50 MiB | 40.46 MiB |
| 最终 GLB 平均面数 | 40,000 | 967,233 |

观察中，混元在杯子文字和魔方色块上较清晰，TRELLIS.2 在陶罐细纹和铃铛金属观感上更突出。这些是 AI 辅助视觉审阅，样本小，继续用 GSO 比较。两者预处理、面数及材质输出设置不同，耗时是各自完整配置的实测。

## 2026-11-09：混元 GSO 开发集

10 个开发对象 × 形状采样 50/30/20 步 × 种子 42/123，共 60 次，全部完成；白模独立保存，纹理副本减至 40,000 面。纹理扩散步数固定 30。

| 形状步数 | 次数 | 平均进程耗时 |
|---|---:|---:|
| 50 | 20 | 109.17 秒 |
| 30 | 20 | 101.92 秒 |
| 20 | 20 | 101.89 秒 |

两次 GPU 作业占用约 1.77 小时。生成完成和文件核验已完成；几何指标、系统性的人工质量评价尚未完成，无法仅凭耗时确定最佳画质。部分冰箱和音箱侧面出现额外图案与文字，后续用 TRELLIS.2 进行对照。

历史批次位于 `experiments/asset3d-gso-v1-20261108/`，原始计划和 60 次运行记录已保留。核验并重建 viewer 索引：

```bash
python scripts/run_batch.py experiments/asset3d-gso-v1-20261108/batch.yaml
```

该命令检查已有结果，不启动 GPU。新的混元重跑使用 `experiments/hunyuan2-gso-dev-rerun/batch.yaml` 和 `slurm/hunyuan2_gso_dev.sbatch`，使用当前共用 runner，历史运行采用独立进程，比较耗时时需记录这一变化。新机器需要单独复制历史 GLB；Git 不包含它们。

## 留存的证据

完整逐次记录、核验摘要和八视角对比图保留在 `docs/results/`：

- [五图详细报告](results/pilot03/README.md)、[逐项记录](results/pilot03/runs.csv)、[杯子八视角示例](results/pilot03/gallery/thin-seed-123.jpg)。
- [混元开发集详细报告](results/gso-dev-v1/README.md)、[逐项记录](results/gso-dev-v1/runs.json)、[核验摘要](results/gso-dev-v1/verification.json)。

这些文件是历史证据；当前安装与运行命令以 [服务器准备](SERVER_SETUP.md) 和 [TRELLIS.2 实验](TRELLIS2_GSO_DEV_GUIDE.md) 为准。
