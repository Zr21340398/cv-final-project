# 数据集与 viewer

## GSO 数据

本项目使用 Google Scanned Objects（GSO）扫描网格。来源及许可、原始对象下载地址在 `data/manifests/gso-selection.csv` 和 `gso-selection.metadata.json`；[GSO 官方介绍](https://research.google/blog/scanned-objects-by-google-research-a-dataset-of-3d-scanned-common-household-items/)及 [GSO 论文](https://arxiv.org/abs/2204.11918)。

第一版选取 30 个对象：10 个开发、20 个测试，按简单实心、细结构、非对称、图案、复杂形状分组。开发对象 ID 为 `gso_01`、`02`、`07`、`08`、`13`、`14`、`19`、`20`、`25`、`26`。名称与全部 30 个对象的链接见来源表。数据划分以对象为单位，测试对象没有参与本次开发实验。

```text
datasets/gso-v1/data/
  raw/                             原始扫描与材质
  rendered/gso-formal-v1/<对象>/   固定视角 PNG、参考 GLB、相机记录
  manifests/gso-formal-v1.csv      30 对象清单
  manifests/gso-dev-v1.csv         10 开发对象清单
```

生成的单视角 PNG 和归一化参考模型已经在本机准备；服务器操作见 [服务器指南](SERVER_SETUP.md)。重新下载原始对象后需按固定视角重新渲染，才能得到可比较的输入。清单中的 ID 与文件相对路径供批次选择；项目对选中对象记录图片与参考模型哈希。

## 使用 viewer

Windows 双击 `gso-viewer/start.bat`，或在项目根目录运行 `python gso-viewer/server.py --open`。浏览器默认打开三个空窗口；点击加号选择本地 GLB，可添加窗口，左键旋转、滚轮缩放、右键平移。点击“实验预设”，选择实验、对象、种子和模型类型，可一起查看参考模型与各方案。

viewer 依据 `viewer-manifest.json` 中的文件路径加载 GLB；文件名可自行指定。预设默认发现 `experiments/<批次>/results/viewer-manifest.json` 和历史目录，选择栏随实验内容变化。清单、图片及模型需要在数据根目录内；文件移动后可运行：

```powershell
.\.venv\Scripts\asset3d.exe viewer-index --experiment experiments/trellis2-gso-dev-v1/results --output experiments/trellis2-gso-dev-v1/results/viewer-manifest.json --reference-dir datasets/gso-v1/data/rendered/gso-formal-v1 --overwrite
```

viewer 的自定义清单字段和完整例子保留在 [viewer 接入参考](../gso-viewer/README.md)。它提供交互式观察，定量几何评价需单独运行评价流程。GLB 未自动对齐时需检查朝向。
