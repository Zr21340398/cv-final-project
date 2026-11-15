# 预实验操作入口（现行目录）

代码获取、数据与权重下载统一见 [DATA_AND_MODELS.md](DATA_AND_MODELS.md)，首次 GPU 环境安装见 [HPC4_SETUP.md](HPC4_SETUP.md)。旧的本地源码/数据打包上传步骤已停用。

本项目已完成的五图预实验在 `docs/results/pilot03/`，方法见 [PILOT_METHOD.md](PILOT_METHOD.md)。当前 GSO 正式开发批次操作见 [TRELLIS2_GSO_DEV_GUIDE.md](TRELLIS2_GSO_DEV_GUIDE.md)。

如需另做五图预实验，保留现有 `asset3d pilot-prepare`、`pilot-init`、`pilot-run` 接口；两模型在各自环境执行，使用自己的新输出目录。每个命令可通过 `asset3d <命令> --help` 查看参数。GSO 正式批次使用 `scripts/run_batch.py` 和 `experiments/<批次>/batch.yaml`，数据从共享 datasets 目录读取。
