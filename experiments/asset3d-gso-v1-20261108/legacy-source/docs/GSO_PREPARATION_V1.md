# GSO 数据准备与 CPU 检查报告

2026-11-08。本轮本地数据准备和 CPU 技术检查已完成，没有提交学校 GPU 作业。
**技术就绪，人工来源验收待确认；尚未进行 GSO 模型生成或正式质量评估。**

## 已准备的文件

| 项目 | 数量 | 位置（相对项目根目录） |
|---|---:|---|
| 原始 ZIP 备份 | 30 | `data/raw/gso/.archives/` |
| 原包解压文件 | 330 | `data/raw/gso/gso_XX/` |
| 带原始贴图的规范化参考 GLB | 30 | `data/rendered/gso-formal-v1/gso_XX/reference_normalized.glb` |
| 1024×1024 RGBA 参考视图 | 240 | 每对象 `view-000.png` 至 `view-007.png` |
| 实际配置的 512×512 RGBA 输入 | 30 | `data/rendered/gso-formal-v1/preprocessed-inputs/` |
| 多视角审阅页 | 30 组 | [打开本地审阅页](../data/rendered/gso-formal-v1/review/index.html) |

运行清单为 [gso-formal-v1.csv](../data/manifests/gso-formal-v1.csv)，保留原定 10 dev / 20 test、五类各 2 dev / 4 test，未替换对象。
ZIP 总计 204,264,245 字节，原包解压总计 361,398,833 字节。包含原包、原文件、参考输出及预处理输入的 720 文件共约 1.01 GB，校验值见 [gso-data-sha256.txt](../data/manifests/gso-data-sha256.txt)。

原始文件和大图保存在本地，仍由 `.gitignore` 排除；本轮没有上传它们到 GitHub。
来源为 Google Research 的 [Google Scanned Objects](https://research.google/blog/scanned-objects-by-google-research-a-dataset-of-3d-scanned-common-household-items/)，按原包 CC BY 4.0 保留署名、来源、许可与压缩原件。

## 技术检查结果

- 30 个 ZIP 的 CRC/SHA256，以及 330 个解压文件的 SHA256 全部匹配。
- 30 个可视网格的坐标、面积、UV 和真实贴图均有效；使用 SDF 的 visual 网格，未使用 collision 网格。
- 240 张图片均为可读的 1024×1024 RGBA，主体未被视框裁切，背景透明；开发与测试使用完全相同的相机、投影、采样及材质渲染协议。
- 30 个参考 GLB 内嵌纹理的解码 RGBA 像素与原始 PNG 完全一致。
- 原始与参考面数逐项相同，范围 3,202–52,216 面。按记录的坐标变换比较，最大双向最近顶点误差为 **5.93×10⁻⁸**，小于 3×10⁻⁶ 的验证阈值。
- 正式三档配置的预处理仅执行 `keep`、512 像素、padding 0.2；不调用抠图器、网络或模型。三档步数得到逐像素相同的输入，透明留白和主体范围检查全部通过。
- CPU 回归测试 **112 passed、1 skipped**；跳过的是缺少可选 Gradio 依赖的界面测试。Ruff 与差异格式检查通过。

开发集和测试集的 `technical_ready` 均为 `true`。`ready` 仍为 `false`，唯一待办代码为 `source_not_accepted`：来源人工验收没有由程序代填。
逐对象证据、哈希、AI 审阅说明与检查结果见 [完整审计记录](../data/manifests/gso-preparation-v1.audit.json)。

## 准备过程中修正的问题

1. **OBJ 坐标轴：** GSO 为 Z-up；显式 `--obj-z-up` 保留原坐标，防止 Blender 默认 OBJ Y-up 导入造成物体横躺。30 个 SDF 均无额外 pose/scale，没有按生成结果为个别对象旋转视角。
2. **纹理引用：** 原包 MTL 只写 `texture.png`，实际图片位于 `materials/textures/`。渲染时通过 `--texture-root` 唯一匹配绑定，原始 OBJ、MTL 和 PNG 不修改。缺失或歧义会在渲染前报错。
3. **坐标证据：** 保存原始 OBJ→规范化渲染空间→glTF Y-up 参考空间的变换，并用实际导出几何复核。这不等于已经校准混元输出与参考的坐标关系，后者需要真实 GPU 首例。

复现某对象的参考渲染时使用新输出目录：

```bash
asset3d render --mesh data/raw/gso/gso_01/meshes/model.obj \
  --output data/rendered/gso-new-version/gso_01 \
  --views 8 --resolution 1024 --obj-z-up \
  --texture-root data/raw/gso/gso_01/materials/textures \
  --blender /Applications/Blender.app/Contents/MacOS/Blender
```

本轮为 Blender 4.5.15 LTS、Cycles CPU、32 samples、seed 2026、统一正交相机。已有版本保留，不覆盖其来源证据。

## 保留的来源限制

- `gso_14` 水罐和 `gso_24` 运动鞋各含两个几何组件，未擅自合并或删去。
- `gso_15` 吹风机有 1 个零面积面；白色带字片是原有安全标签，不是背景杂物。
- `gso_16` 茶壶有 2 个零面积微片，网格非闭合。八视角未见宏观破坏，仍保留原始记录，不把“技术通过”解释为完美扫描。
- 白瓷、高亮金属和浅色物体存在强高光、低对比或扫描烘焙光照。GSO 颜色贴图不能作为金属度、粗糙度的独立真值。
- 剪刀、夹具、压汁器等在原始扫描中平放；输入视角可能出现缩短和自遮挡，按统一规则保留这些难例。

几何指标的 CPU sanity check 仅使用合成点云/立方体验证程序；没有把这些检查数值当作混元生成结果或正式 Chamfer 得分。

## 进入学校 GPU 前

AI 已查看全部 30 对象的 240 个参考视图，未发现阻断性的错轴、缺贴图、裁切或背景杂物；这属于来源检查，**不是人工验收或生成结果的盲评分**。
来源表状态为 `prepared_ai_review`；[人工来源检查表](../data/manifests/gso-human-qa-v1.csv) 保留空栏。确认审阅页中的几何、贴图与朝向后，才记录人工 `accepted`。

下一阶段需要学校 L20 执行混元开发首例，确认真实推理、Paint、GLB 导出、坐标关系和耗时，再决定后续开发矩阵预算。
按用户要求，进入学校 GPU 步骤前先提醒；本轮只完成本地准备，没有提交、取消或重跑任何学校作业。
