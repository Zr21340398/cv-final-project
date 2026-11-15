# 共享数据

GSO 准备后的数据位于 `gso-v1/data/`。每个批次通过对象 ID 引用共享清单。首次将现有 data 目录传输到服务器一次，或按来源表下载原始对象并按固定协议处理。具体方法见 [统一准备指南](../docs/DATA_AND_MODELS.md)，不使用本地数据打包脚本。

大文件被 Git 忽略。数据来源与许可记录在根目录 `data/manifests/`；旧混元批次的小型溯源记录在 `experiments/asset3d-gso-v1-20261108/provenance/`。
