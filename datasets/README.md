# 共享数据目录

将已核验的 GSO 数据包解压到 `datasets/gso-v1/`。其内部保留 `data/manifests/` 和 `data/rendered/` 的相对布局。批次通过 `experiments/<批次>/batch.yaml` 引用共享清单和对象 ID；图片和网格只保存一份。子目录的大文件被 Git 忽略，数据来源和许可记录保留在仓库 `data/manifests/`。详见 `docs/TRELLIS2_GSO_DEV_GUIDE.md`。
