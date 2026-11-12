# 单图 3D 资产生成：模型选型与 GSO 正式数据准备

项目先用相同五个物体、两个种子比较 **TRELLIS.2 与混元 3D 2.0 的官方单图流程**，随后以混元开展 GSO 开发集实验。无需先生成六视角图。

**2026-11-09：GSO 混元开发集 60/60 项生成及独立技术核验通过。** 查看 [完成与成本报告](docs/results/gso-dev-v1/README.md)、[逐项记录](docs/results/gso-dev-v1/runs.json) 和 [核验摘要](docs/results/gso-dev-v1/verification.json)。50/30/20 步平均完整生成时间分别为 109.17/101.92/101.89 秒；质量评价、人工评分与 GSO Chamfer 尚未完成，测试集尚未生成。本次发布报告和记录，运行源码指纹及原始产物保存位置见报告。

**正式数据已确定为 GSO：阅读 [GSO 数据准备与选样说明](docs/GSO_DATASET.md)。**
已选定第一版 10 个开发对象与 20 个测试对象，详见 [对象清单](docs/GSO_SELECTION_V1.md)。开发集已执行，人工来源验收仍待完成；正式参数选择还需结合开发集质量评价。数据准备说明和仓库中的初始规划需与最新结果报告中的冻结实验范围区分。

**查看模型：使用 [本地 3D 模型工作台](gso-viewer/README.md)。** 可以手动添加 GLB，也可以用实验预设并排查看 GSO 参考与各方案结果。新的批量实验会生成展示清单；模型文件需另外下载到本地。

**运行模型选型预实验：从 [预实验实操说明](docs/PILOT_GUIDE.md) 开始。**
包含上传、模型权限、两个环境、下载、共用去背景、单例验证、Slurm 批处理、评分和排错。
方法与版本依据见 [PILOT_METHOD.md](docs/PILOT_METHOD.md)。

当前代码提供两模型适配、成对实验、白模/PBR GLB 导出、运行记录和评价工具。
**pilot03 已在学校 L20 完成 20/20 次真实生成。** 查看 [五图预实验结果与完整多视角对比](docs/results/pilot03/README.md)、[逐项统计](docs/results/pilot03/runs.csv) 与 [完整结果附件](https://github.com/Zr21340398/cv-final-project/releases/tag/pilot03-2026-11-07)。本轮建议混元作为较低成本的展示基线，TRELLIS.2 保留为细节和材质对照；结论边界与早期失败记录见报告。工程测试验收范围见 [VALIDATION.md](docs/VALIDATION.md)。

## 预实验命令入口

先按实操说明安装环境并准备数据，不要直接在笔记本执行 GPU 推理。

```bash
# 混元环境中一次抠图；两组共用同一输入
asset3d pilot-prepare --manifest data/manifests/pilot.csv --output data/prepared/pilot01
asset3d pilot-init --manifest data/prepared/pilot01/objects.csv --seeds 42 123 --output results/pilot01

# 在分别激活的环境里执行；或使用 slurm/pilot.sbatch
asset3d pilot-run --experiment results/pilot01 --name trellis2 --limit 1
asset3d pilot-run --experiment results/pilot01 --name hunyuan2 --limit 1
# 首例成功后，两组各自添加 --resume 继续全部计划
asset3d pilot-report --experiment results/pilot01 --output results/pilot01/summary
asset3d pilot-render --experiment results/pilot01 --blender blender --views 8
```

五个物体 × 两个种子 × 两组，共 20 个结果。无三维真值的照片不计算 Chamfer；
带真值的开发数据可用 pilot-evaluate，需先校准坐标。

## 代码结构

| 文件/目录 | 用途 |
|---|---|
| configs/trellis2.yaml | TRELLIS.2 固定权重、辅助模型、分辨率、PBR 导出设置 |
| configs/hunyuan2_pilot.yaml | 混元标准单图流程，使用共用透明前景 |
| src/asset3d/backends/trellis2.py | 官方 TRELLIS.2 接口与离线权重解析 |
| src/asset3d/backends/hunyuan2.py | 原有混元接口 |
| src/asset3d/pipeline.py | 同一输出约定、哈希、状态、失败恢复 |
| src/asset3d/pilot.py | 冻结计划、独立进程运行、成对汇总、统一渲染 |
| scripts/install_trellis2_hpc.sh | TRELLIS.2 独立安装，固定 CUDA 扩展提交 |
| slurm/pilot.sbatch | 两组作业共用入口，自动选择环境 |
| data/manifests/pilot.example.csv | 五样本格式模板，需要真实图片 |
| gso-viewer/ | 本地 Babylon.js 模型浏览与三档步数对比 |
| tests/ | CPU 工程测试，合成网格仅作测试夹具 |

每次生成保存 input.png、foreground.png、shape_raw.glb、asset.glb、manifest.json。
TRELLIS 的形状与材质生成合并计时，另记 PBR 烘焙；
混元保留原来的 shape/texture 时间。完整成本看 wall/process_wall，不把局部时间当总耗时。
同一份 GLB 不能恢复 TRELLIS 原生材质状态，因此失败恢复会重新生成；完成结果可验证后跳过。

## 本地开发与打包

```powershell
.\.venv\Scripts\python.exe -m asset3d.cli doctor
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe scripts/package_project.py
```

dist/asset3d-source.tar.gz 只包含源码、配置、说明和清单模板；
不包含环境、权重、课程 PDF、用户图片或真实结果。

## 保留的旧功能

configs/baseline.yaml、medium.yaml、fast.yaml 与原 Gradio 界面仍用于混元 50/30/20 步实验，
本轮模型选型通过新的命令行/Slurm 流程完成，不在一个环境混装两个演示界面。

实验说明：[GSO 正式实验协议](docs/EXPERIMENTS.md)。旧资料：[混元安装](docs/HPC4_SETUP.md)、
[原架构](docs/ARCHITECTURE.md)。课程 PDF 与原用户文件未改动。
