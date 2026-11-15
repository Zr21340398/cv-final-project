# 单图 3D 资产生成与实验工作台

本项目使用混元 3D 2.0 和 TRELLIS.2，将单张物体图片生成带材质的 GLB，并提供 GSO 数据管理、批量实验和 3D viewer。

## 文档入口

1. [项目目标、原理和代码结构](docs/PROJECT.md)
2. [服务器从零准备](docs/SERVER_SETUP.md)
3. [数据集和 viewer](docs/DATASET_VIEWER.md)
4. [历史实验记录](docs/EXPERIMENT_HISTORY.md)
5. [TRELLIS.2 GSO 开发集实验](docs/TRELLIS2_GSO_DEV_GUIDE.md)

代码、模型配置和批次定义由 Git 管理；`datasets/` 中的数据、`models/` 中的权重与实验生成结果单独存放。服务器项目目录是 `~/project/cv-final-project/`。旧混元实验已迁入 `experiments/asset3d-gso-v1-20261108/`；新 TRELLIS.2 批次尚待服务器运行。
