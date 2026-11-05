# 预实验的五张输入图片

下载日期：2026-10-27。图片来自 Wikimedia Commons，保留原图，只修改文件名。

## 选择理由与来源

| 文件 | 物体与观察重点 | 作者/署名 | 来源与许可 |
|---|---|---|---|
| [simple.jpg](simple.jpg) | **陶罐**：整体轮廓、圆弧表面、上下比例。白底且结构简单，适合先跑通流程。 | Amada44 | [来源](https://commons.wikimedia.org/wiki/File:Clay_vase_5882.jpg) · [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| [thin.jpg](thin.jpg) | **带柄陶瓷杯**：杯柄是否连通、孔洞是否保留、杯口与杯壁是否合理。杯身文字可辅助观察纹理。 | Auckland Museum | [来源](https://commons.wikimedia.org/wiki/File:Mug_(AM_6100-1).jpg) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| [asymmetric.jpg](asymmetric.jpg) | **花纹茶壶**：壶嘴、把手、壶盖的相对位置和比例。花纹与光照也增加一些难度。 | Auckland Museum | [来源](https://commons.wikimedia.org/wiki/File:Teapot_and_cover_(AM_1985.425-2).jpg) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| [pattern.jpg](pattern.jpg) | **彩色魔方**：方体棱角、格子分布、颜色边界及纹理在各面的位置。背景仍有浅色布纹，预处理时检查抠图。 | Thenror | [来源](https://commons.wikimedia.org/wiki/File:Rubik%27s_Cube_3x3.jpg) · [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| [material.jpg](material.jpg) | **铜铃**：金属外观、细长手柄与铃口轮廓。这是稍难的样例：反光和贴近主体的阴影需要在抠图后检查。 | Thamizhpparithi Maari | [来源](https://commons.wikimedia.org/wiki/File:A_brass_bell.JPG) · [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) |

## 怎么使用

已生成 `data/manifests/pilot.csv`，每行对应一张照片。两个模型使用相同的五张图和共用预处理结果。保持已选定的图片与随机种子固定，记录所有结果。

按 `docs/PILOT_GUIDE.md` 第 8 节上传五张 JPG 和清单，再运行共用抠图。查看输出时，重点检查杯柄和壶柄的孔洞、壶嘴、铜铃手柄，以及主体旁的阴影。抠图有问题时先修正共用输入，再同时供给两个模型。

铜铃原图带有 EXIF 方向信息；项目预处理会读取它并转正。原始文件保留摄影元数据。

这组实拍照片用于初步比较外观、结构合理性、运行时间和资源消耗。它们没有配套真实三维网格，清单的 `reference` 留空，`split` 为 `real`。背面形状只能检查是否合理；计算 Chamfer Distance 等几何误差需要另外准备带参考网格的数据。五张图的结果适合作为小规模选型依据。

图片可能出现在公开训练数据中，目前未核实两个模型的训练集是否包含它们。报告中应写明这些是公开实拍样例。

## 在报告里署名

在使用图片的页面或参考资料中保留作者、图片来源链接及许可链接。若对图片做裁剪、去背景或其他改动，注明改动；分享修改后的 CC BY-SA 图片时，按对应许可要求采用相同或兼容许可。详细下载地址、尺寸和 SHA-256 校验值见 `sources.json`。
