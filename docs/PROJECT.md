# 项目目标、原理和代码结构

## 项目目标

课程项目目标是把单张物体照片转换为可查看、带颜色或材质的三维资产，导出 GLB，并通过几何质量、视觉效果和输入一致性进行评价。项目使用已有模型权重进行推理，同时开发数据管理、批量实验、评估和展示流程。

## 从一张图片到三维模型

```text
输入照片 → 前景与尺寸处理 → 三维生成 → GLB 导出 → 质量评价与 viewer 展示
```

图片只直接提供一个角度的信息。模型结合训练中学到的物体规律推测完整形状与不可见部分，生成结果中的细节需要用参考数据和人工观察检验。

- **混元 3D 2.0**：先由形状模型生成网格（白模），再由 Paint 根据图片生成多视角外观并融合到纹理。当前配置会为上色副本减面，原始白模单独保存。[混元论文](https://arxiv.org/abs/2501.12202)。
- **TRELLIS.2**：从图片特征生成稀疏空间结构、形状和材质潜表示，再解码并烘焙为带 PBR 材质的 GLB。当前使用 1024 cascade，生成与材质推理作为相连流程执行。[TRELLIS.2 论文](https://arxiv.org/abs/2512.14692)。

## 数据和实验

GSO 的参考网格用于渲染输入图片，并为几何、纹理比较提供参考；10 个开发对象用于探索方案，20 个测试对象留作最终评价。生成模型与参考坐标需要校准后再算距离。视觉评价还需覆盖多个视角，并保留失败结果。详细情况见 [数据与 viewer](DATASET_VIEWER.md) 与 [历史记录](EXPERIMENT_HISTORY.md)。

## 代码与目录

```text
src/asset3d/
  backends/hunyuan2.py       混元形状与 Paint 适配
  backends/trellis2.py       TRELLIS.2 原生生成与 PBR 导出
  pipeline.py                预处理、生成、记录和导出
  batch_definition.py        根据批次配置选择共享数据、冻结配置
  experiments.py             批量调度与 viewer 索引更新
  evaluation/                几何和外观评价
  viewer_manifest.py         面向 viewer 的实验清单
configs/                     模型参数
scripts/  slurm/             执行入口、安装脚本与集群调度
datasets/                    本机或服务器共享数据，Git 不保存大文件
models/                      权重缓存，不提交 Git
experiments/                 每次实验的配置、记录和结果
gso-viewer/                  本地 Babylon.js 模型工作台
```

代码、选样清单和批次定义通过 Git 管理；模型权重、原始数据和 GLB 单独准备。原混元实验的源码快照留在其批次中用于追溯；当前执行使用根目录代码。服务器初次准备见 [服务器指南](SERVER_SETUP.md)。
